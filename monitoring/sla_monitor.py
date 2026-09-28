#!/usr/bin/env python3
"""
sla_monitor.py - Supervision SLA de l'environnement OpenStack (Partie 3).

A chaque execution (toutes les 5 minutes via cron) le script :
  1. s'authentifie aupres de Keystone et recupere le catalogue de services ;
  2. verifie les API Nova, Neutron, Keystone (et Ceilometer s'il est deploye) ;
  3. releve l'etat des instances et la latence reseau (connexion TCP) ;
  4. enregistre l'echantillon dans data/history.jsonl ;
  5. calcule la disponibilite journaliere, la compare a l'objectif de sla.json,
     ecrit le rapport dans sla.json ("last_report") et dans reports/.

Aucune dependance externe : bibliotheque standard Python 3 uniquement.
Code de sortie : 0 = SLA respecte, 2 = SLA viole, 1 = erreur de configuration.
"""

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEFAULT_CONFIG = BASE / "sla.json"
DEFAULT_ENV = BASE / "sla.env"
HISTORY_FILE = BASE / "data" / "history.jsonl"
REPORTS_DIR = BASE / "reports"
ALERTS_FILE = REPORTS_DIR / "alerts.log"


# --------------------------------------------------------------------------
# Utilitaires
# --------------------------------------------------------------------------
def now_utc():
    return datetime.now(timezone.utc)


def load_env_file(path):
    """Charge un fichier KEY=VALUE ; les variables deja definies restent prioritaires."""
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def http_json(method, url, body=None, token=None, timeout=10):
    """Requete HTTP JSON. Retourne (statut, en-tetes, donnees, latence_ms)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("X-Auth-Token", token)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status, headers = response.status, response.headers
    except urllib.error.HTTPError as err:
        raw, status, headers = err.read(), err.code, err.headers
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    try:
        payload = json.loads(raw) if raw else {}
    except ValueError:
        payload = {}
    return status, headers, payload, latency_ms


def catalog_url(catalog, service_types):
    """Retourne l'URL publique du premier type de service trouve dans le catalogue."""
    for entry in catalog:
        if entry.get("type") in service_types:
            for endpoint in entry.get("endpoints", []):
                if endpoint.get("interface") == "public":
                    return endpoint["url"].rstrip("/")
    return None


def result(ok, latency_ms=None, **extra):
    out = {"ok": ok, "latency_ms": latency_ms}
    out.update(extra)
    return out


# --------------------------------------------------------------------------
# Verifications (un echantillon)
# --------------------------------------------------------------------------
def authenticate(timeout):
    auth_url = os.environ["OS_AUTH_URL"].rstrip("/")
    if not auth_url.endswith("/v3"):
        auth_url += "/v3"
    payload = {"auth": {
        "identity": {"methods": ["password"], "password": {"user": {
            "name": os.environ["OS_USERNAME"],
            "domain": {"name": os.environ.get("OS_USER_DOMAIN_NAME", "Default")},
            "password": os.environ["OS_PASSWORD"]}}},
        "scope": {"project": {
            "name": os.environ.get("OS_PROJECT_NAME", "admin"),
            "domain": {"name": os.environ.get("OS_PROJECT_DOMAIN_NAME", "Default")}}}}}
    status, headers, data, latency = http_json("POST", auth_url + "/auth/tokens", payload, timeout=timeout)
    if status != 201:
        raise RuntimeError("Keystone HTTP %s" % status)
    return headers.get("X-Subject-Token"), data["token"]["catalog"], latency


def check_nova(url, token, timeout):
    status, _, data, latency = http_json("GET", url + "/servers/detail", token=token, timeout=timeout)
    if status != 200:
        return result(False, latency, error="HTTP %s" % status), []
    instances = []
    for server in data.get("servers", []):
        floating = None
        for entries in server.get("addresses", {}).values():
            for entry in entries:
                if entry.get("OS-EXT-IPS:type") == "floating":
                    floating = entry.get("addr")
        instances.append({"name": server.get("name"), "status": server.get("status"),
                          "floating_ip": floating})
    return result(True, latency, instances_count=len(instances)), instances


def check_neutron(url, token, timeout):
    status, _, data, latency = http_json("GET", url + "/v2.0/agents", token=token, timeout=timeout)
    if status != 200:
        return result(False, latency, error="HTTP %s" % status)
    agents = data.get("agents", [])
    alive = sum(1 for agent in agents if agent.get("alive"))
    return result(alive >= 1, latency, agents_alive=alive, agents_down=len(agents) - alive)


def check_ceilometer(url, token, timeout):
    if not url:
        return {"ok": None, "latency_ms": None, "status": "not_deployed"}
    status, _, _, latency = http_json("GET", url, token=token, timeout=timeout)
    return result(status < 500, latency, status="deployed")


def tcp_latency(ip, port, timeout):
    """Latence reseau : duree d'une connexion TCP vers l'instance (ms), None si echec."""
    start = time.perf_counter()
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return round((time.perf_counter() - start) * 1000, 1)
    except OSError:
        return None


def take_sample(cfg):
    timeout = cfg["thresholds"]["request_timeout_seconds"]
    port = cfg["thresholds"]["network_probe_port"]
    sample = {"timestamp": now_utc().isoformat(timespec="seconds"), "services": {}, "instances": []}
    try:
        token, catalog, ks_latency = authenticate(timeout)
        sample["services"]["keystone"] = result(True, ks_latency)
    except Exception as err:  # authentification impossible : rien d'autre n'est testable
        sample["services"]["keystone"] = result(False, None, error=str(err))
        for name in ("nova", "neutron"):
            sample["services"][name] = result(False, None, error="pas de jeton Keystone")
        sample["services"]["ceilometer"] = {"ok": None, "latency_ms": None, "status": "unknown"}
        sample["ok"] = False
        return sample

    nova_url = catalog_url(catalog, ("compute",))
    neutron_url = catalog_url(catalog, ("network",))
    ceilometer_url = catalog_url(catalog, ("metering", "metric"))

    instances = []
    try:
        sample["services"]["nova"], instances = check_nova(nova_url, token, timeout)
    except Exception as err:
        sample["services"]["nova"] = result(False, None, error=str(err))
    try:
        sample["services"]["neutron"] = check_neutron(neutron_url, token, timeout)
    except Exception as err:
        sample["services"]["neutron"] = result(False, None, error=str(err))
    try:
        sample["services"]["ceilometer"] = check_ceilometer(ceilometer_url, token, timeout)
    except Exception as err:
        sample["services"]["ceilometer"] = result(False, None, error=str(err))

    for instance in instances:
        if instance["status"] == "ACTIVE" and instance["floating_ip"]:
            instance["network_latency_ms"] = tcp_latency(instance["floating_ip"], port, timeout)
        else:
            instance["network_latency_ms"] = None
    sample["instances"] = instances

    services_ok = all(sample["services"].get(name, {}).get("ok") for name in cfg["services"])
    no_error = all(instance["status"] != "ERROR" for instance in instances)
    sample["ok"] = bool(services_ok and no_error)
    return sample


# --------------------------------------------------------------------------
# Historique et rapport
# --------------------------------------------------------------------------
def append_history(sample):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(sample) + "\n")


def read_history(day):
    samples = []
    if HISTORY_FILE.is_file():
        for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            try:
                sample = json.loads(line)
            except ValueError:
                continue
            if sample.get("timestamp", "").startswith(day):
                samples.append(sample)
    return samples


def average(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def percent(part, total):
    return round(100.0 * part / total, 2) if total else None


def build_report(cfg, samples, day):
    total = len(samples)
    ok_count = sum(1 for s in samples if s["ok"])
    availability = percent(ok_count, total)
    target = cfg["availability_target"]

    services = {}
    for name in cfg["services"] + cfg.get("optional_services", []):
        entries = [s["services"].get(name) for s in samples if s["services"].get(name)]
        measured = [e for e in entries if e.get("ok") is not None]
        services[name] = {
            "availability_percent": percent(sum(1 for e in measured if e["ok"]), len(measured)),
            "avg_latency_ms": average([e.get("latency_ms") for e in measured]),
            "status": "surveille" if measured else "non deploye / non mesure",
        }

    per_instance = {}
    for sample in samples:
        for instance in sample["instances"]:
            data = per_instance.setdefault(instance["name"], {"seen": 0, "active": 0, "lat": []})
            data["seen"] += 1
            data["active"] += 1 if instance["status"] == "ACTIVE" else 0
            data["lat"].append(instance.get("network_latency_ms"))
    last_status = {}
    for sample in samples:
        for instance in sample["instances"]:
            last_status[instance["name"]] = instance["status"]
    instances = {
        name: {"uptime_percent": percent(d["active"], d["seen"]),
               "avg_network_latency_ms": average(d["lat"]),
               "current_status": last_status.get(name, "inconnu")}
        for name, d in per_instance.items()}

    met = availability is not None and availability >= target
    return {
        "generated_at": now_utc().isoformat(timespec="seconds"),
        "evaluation_date": day,
        "samples": total,
        "samples_ok": ok_count,
        "availability_percent": availability,
        "target_percent": target,
        "sla_met": met,
        "verdict": "OBJECTIF RESPECTE" if met else "OBJECTIF NON RESPECTE",
        "services": services,
        "instances": instances,
        "network_latency_avg_ms": average(
            [d["avg_network_latency_ms"] for d in instances.values()]),
    }


def format_report(report):
    lines = [
        "=== Rapport SLA - %s ===" % report["evaluation_date"],
        "Genere le          : %s (UTC)" % report["generated_at"],
        "Echantillons       : %s (dont %s disponibles)" % (report["samples"], report["samples_ok"]),
        "Disponibilite      : %s %%  (objectif : %s %%)" % (
            report["availability_percent"], report["target_percent"]),
        "Verdict            : %s" % report["verdict"],
        "", "Services :"]
    for name, svc in report["services"].items():
        lines.append("  - %-11s disponibilite=%-8s latence moyenne=%-9s (%s)" % (
            name, fmt(svc["availability_percent"], " %"), fmt(svc["avg_latency_ms"], " ms"), svc["status"]))
    lines += ["", "Instances :"]
    for name, inst in report["instances"].items():
        lines.append("  - %-18s etat=%-8s uptime=%-8s latence reseau=%s" % (
            name, inst["current_status"], fmt(inst["uptime_percent"], " %"),
            fmt(inst["avg_network_latency_ms"], " ms")))
    return "\n".join(lines) + "\n"


def fmt(value, unit=""):
    return "n/a" if value is None else "%s%s" % (value, unit)


def write_json_atomic(path, data):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def save_report(cfg, config_path, report):
    cfg["last_report"] = report
    write_json_atomic(config_path, cfg)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    text = format_report(report)
    (REPORTS_DIR / ("sla_report_%s.txt" % report["evaluation_date"])).write_text(text, encoding="utf-8")
    write_json_atomic(REPORTS_DIR / ("sla_report_%s.json" % report["evaluation_date"]), report)
    return text


def raise_alert(report):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    message = "%s ALERTE SLA : disponibilite %s %% < objectif %s %% (%s/%s echantillons)" % (
        report["generated_at"], report["availability_percent"], report["target_percent"],
        report["samples_ok"], report["samples"])
    with ALERTS_FILE.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")
    print(message, file=sys.stderr)


# --------------------------------------------------------------------------
# Programme principal
# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Supervision SLA OpenStack")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="fichier sla.json")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV), help="fichier des identifiants OpenStack")
    parser.add_argument("--report-only", action="store_true",
                        help="ne fait pas de nouvelle mesure, recalcule le rapport du jour")
    parser.add_argument("--reset-history", action="store_true", help="efface l'historique des mesures")
    args = parser.parse_args()

    config_path = Path(args.config)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))

    if args.reset_history:
        HISTORY_FILE.unlink(missing_ok=True)
        print("Historique efface.")
        return 0

    if not args.report_only:
        load_env_file(args.env_file)
        missing = [k for k in ("OS_AUTH_URL", "OS_USERNAME", "OS_PASSWORD") if not os.environ.get(k)]
        if missing:
            print("Variables manquantes : %s (voir sla.env.example)" % ", ".join(missing), file=sys.stderr)
            return 1
        sample = take_sample(cfg)
        append_history(sample)
        print("[%s] echantillon %s | %s" % (
            sample["timestamp"], "OK" if sample["ok"] else "ECHEC",
            " ".join("%s=%s" % (n, "ok" if s.get("ok") else ("-" if s.get("ok") is None else "KO"))
                     for n, s in sample["services"].items())))

    day = now_utc().strftime("%Y-%m-%d")
    report = build_report(cfg, read_history(day), day)
    text = save_report(cfg, config_path, report)
    if args.report_only:
        print(text)
    else:
        print("Disponibilite du jour : %s %% (objectif %s %%) -> %s" % (
            report["availability_percent"], report["target_percent"], report["verdict"]))

    if not report["sla_met"]:
        if cfg.get("alert_on_violation") and not args.report_only:
            raise_alert(report)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
