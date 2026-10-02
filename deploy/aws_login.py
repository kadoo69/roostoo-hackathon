"""Browser sign-in for the `hackathon` AWS profile (IAM Identity Center device flow), no key copying.

Run: python3 deploy/aws_login.py  -> open the printed link, approve, done. botocore then refreshes the
short-lived role keys by itself until the Identity Center session ends (its length is set by the
organisers, typically 8-12 h); run it again after that. Replaces the copied keys of deploy/aws_creds.py.
DECISIONS.md#ec2-cutover-2026-10-02
"""
import configparser
import datetime as dt
import hashlib
import json
import os
import time
import webbrowser

import boto3

START_URL = "https://identitycenter.amazonaws.com/ssoins-72238ab4f6d01eca"
SSO_REGION = "us-east-1"
ACCOUNT = "486596084522"
ROLE = "HackathonPermissionSet"
SESSION = "hackathon-sso"
AWS = os.path.expanduser("~/.aws")


def write_config() -> None:
    os.makedirs(AWS, mode=0o700, exist_ok=True)
    cfg = configparser.ConfigParser()
    path = os.path.join(AWS, "config")
    cfg.read(path)
    cfg[f"sso-session {SESSION}"] = {"sso_start_url": START_URL, "sso_region": SSO_REGION,
                                     "sso_registration_scopes": "sso:account:access"}
    cfg["profile hackathon"] = {"sso_session": SESSION, "sso_account_id": ACCOUNT, "sso_role_name": ROLE,
                                "region": "ap-southeast-2"}
    with open(path, "w") as fh:
        cfg.write(fh)
    cred = configparser.ConfigParser()
    cpath = os.path.join(AWS, "credentials")
    cred.read(cpath)
    if cred.has_section("hackathon"):
        cred.remove_section("hackathon")
        with open(cpath, "w") as fh:
            cred.write(fh)


def login() -> None:
    oidc = boto3.client("sso-oidc", region_name=SSO_REGION)
    reg = oidc.register_client(clientName="roostoo-desk", clientType="public",
                               grantTypes=["urn:ietf:params:oauth:grant-type:device_code", "refresh_token"],
                               scopes=["sso:account:access"])
    auth = oidc.start_device_authorization(clientId=reg["clientId"], clientSecret=reg["clientSecret"], startUrl=START_URL)
    url = auth["verificationUriComplete"]
    print(f"Open and approve: {url}\n(code {auth['userCode']})", flush=True)
    try:
        webbrowser.open(url)
    except Exception:                                         # noqa: BLE001
        pass
    deadline = time.time() + auth["expiresIn"]
    while time.time() < deadline:
        time.sleep(max(auth.get("interval", 5), 5))
        try:
            tok = oidc.create_token(clientId=reg["clientId"], clientSecret=reg["clientSecret"],
                                    grantType="urn:ietf:params:oauth:grant-type:device_code",
                                    deviceCode=auth["deviceCode"])
            break
        except oidc.exceptions.AuthorizationPendingException:
            continue
        except oidc.exceptions.SlowDownException:
            time.sleep(5)
    else:
        raise SystemExit("not approved in time; run again")
    now = dt.datetime.now(dt.UTC)
    cache = {"startUrl": START_URL, "region": SSO_REGION, "accessToken": tok["accessToken"],
             "expiresAt": (now + dt.timedelta(seconds=tok["expiresIn"])).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "clientId": reg["clientId"], "clientSecret": reg["clientSecret"],
             "registrationExpiresAt": dt.datetime.fromtimestamp(reg["clientSecretExpiresAt"], dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if tok.get("refreshToken"):
        cache["refreshToken"] = tok["refreshToken"]
    d = os.path.join(AWS, "sso", "cache")
    os.makedirs(d, mode=0o700, exist_ok=True)
    path = os.path.join(d, hashlib.sha1(SESSION.encode()).hexdigest() + ".json")
    with open(path, "w") as fh:
        json.dump(cache, fh)
    os.chmod(path, 0o600)


if __name__ == "__main__":
    write_config()
    login()
    arn = boto3.Session(profile_name="hackathon").client("sts").get_caller_identity()["Arn"]
    print("ok:", arn.split("/")[1])
