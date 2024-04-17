#!/usr/bin/env python

from pyroclient import Client
import requests
from typing import Any, Dict, Optional
import pandas as pd
import secrets
import os

def get_token(api_url: str, login: str, pwd: str) -> str:

    response = requests.post(
        f"{api_url}/login/access-token",
        data={"username": login, "password": pwd},
    )
    if response.status_code != 200:
        raise ValueError(response.json()["detail"])
    return response.json()["access_token"]


def api_request(method_type: str, route: str, headers=Dict[str, str], payload: Optional[Dict[str, Any]] = None):

    kwargs = {"json": payload} if isinstance(payload, dict) else {}

    response = getattr(requests, method_type)(route, headers=headers, **kwargs)
    return response.json()

def get_api_idx(api_list, element, key):
    return [e["id"] for e in api_list if e[key]==element]

api_url = os.environ.get('API_URL')
superuser_login = os.environ.get('SUPERUSER_LOGIN')
superuser_pwd = os.environ.get('SUPERUSER_PWD')

superuser_auth = {
        "Authorization": f"Bearer {get_token(api_url, superuser_login, superuser_pwd)}",
        "Content-Type": "application/json",
    }

sub_path = "_DEV"

devices = pd.read_csv(f"/data/csv/API_DATA{sub_path} - devices.csv")
groups = pd.read_csv(f"/data/csv/API_DATA{sub_path} - groups.csv")
sites = pd.read_csv(f"/data/csv/API_DATA{sub_path} - sites.csv")
users = pd.read_csv(f"/data/csv/API_DATA{sub_path} - users.csv")

print(devices)
print(groups)
print(sites)
print(users)

key = "name"
for group in groups[key]:
    if group != "admins":
        payload = dict(name=group)
        print(payload)
        api_request("post", f"{api_url}/groups/", superuser_auth, payload)

registered_groups = api_request("get", f"{api_url}/groups/", superuser_auth)

groups["api_id"]=[get_api_idx(registered_groups, v, key)[0] for v in groups[key].values]

key = "login"
for i in range(len(users)):
    data = users.iloc[i]
    password = str(secrets.token_urlsafe(12) )
    users.at[i,'password']= password
    group_id = int(groups[groups["id"]==data["group_id"]]["api_id"].values[0])
    payload = dict(login=data["login"], password=password, scope=data["scope"], group_id=group_id)
    print(payload)
    api_request("post", f"{api_url}/users/", superuser_auth, payload)

api_users = api_request("get", f"{api_url}/users/", superuser_auth)
users["api_id"]=[get_api_idx(api_users, v, key)[0] for v in users[key].values]

key = "name"
for i in range(len(sites)):
    data = sites.iloc[i]
    group_id = int(groups[groups["id"]==data["group_id"]]["api_id"].values[0])
    payload = dict(name=data[key], country=data["country"], geocode=str(data["geocode"]), lat=float(data["lat"]), lon=float(data["lon"]), group_id=group_id)    
    print(payload)
    api_request("post", f"{api_url}/sites/", superuser_auth, payload)


key = "login"
for i in range(len(devices)):
    data = devices.iloc[i]
    group_id = int(groups[groups["id"]==data["group_id"]]["api_id"].values[0])
    owner_id = int(users[users["id"]==data["group_id"]]["api_id"].values[0])
    payload = dict(login=data[key], password=data["password"], azimuth=int(data["azimuth"]), pitch=int(data["pitch"]), 
                    lat=float(data["lat"]), lon=float(data["lon"]), elevation=int(data["elevation"]), specs=data["specs"],
                    last_ping=data["last_ping"], angle_of_view=int(data["angle_of_view"]), software_hash=data["software_hash"],
                    owner_id=owner_id, scope=data["scope"], group_id=group_id)
    print(payload)
    r = api_request("post", f"{api_url}/devices/", superuser_auth, payload)

#TODO : logging & testing