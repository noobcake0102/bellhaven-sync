"""Thin client for the CRM API. The only file that talks to the CRM."""
import requests

from . import config


class CRMError(Exception):
    pass


class CRM:
    def __init__(self, token=None, base=None):
        self.base = base or config.API_BASE
        token = token or config.CRM_TOKEN
        if not token:
            raise CRMError("CRM_TOKEN is not set. Copy .env.example to .env and add your token.")
        self.s = requests.Session()
        self.s.headers["Authorization"] = "Bearer " + token

    def _call(self, method, path, **kw):
        r = self.s.request(method, self.base + path, timeout=30, **kw)
        if r.status_code >= 400:
            raise CRMError("%s %s -> %s %s" % (method, path, r.status_code, r.text[:300]))
        return r.json()

    def _list(self, path):
        """Read every page. Stops on the reported total, not on an empty page."""
        out, page = [], 1
        while True:
            body = self._call("GET", path, params={"page": page, "page_size": 100})
            out += body["data"]
            if not body["data"] or len(out) >= body.get("total", 0):
                return out
            page += 1

    def accounts(self):
        return self._list("/accounts")

    def contacts(self):
        return self._list("/contacts")

    def get_account(self, account_id):
        body = self._call("GET", "/accounts/" + account_id)
        return body.get("data", body)

    def update_account(self, account_id, fields):
        body = self._call("PATCH", "/accounts/" + account_id, json=fields)
        return body.get("data", body)

    def create_account(self, fields):
        body = self._call("POST", "/accounts", json=fields)
        return body.get("data", body)
