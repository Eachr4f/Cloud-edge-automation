# README

# Projet Cloud & Edge Computing — Intégration Jenkins & Ansible

| **Auteur** | Achraf Ettanouti |
| --- | --- |
| **Topic** | Cloud et Edge Computing — Technologies de virtualisation |
| **Environnement** | Windows 11 + VirtualBox — VM Ubuntu Server 24.04 (DevStack) |

## Présentation

Ce dépôt regroupe l’implémentation du projet en cinq parties : déploiement OpenStack (DevStack), provisioning d’infrastructure avec Terraform, supervision SLA, automatisation CI/CD avec Jenkins, et gestion de configuration avec Ansible. L’ensemble de l’infrastructure est déployé localement via VirtualBox, conformément aux consignes du projet.

---

## Structure du dépôt

```
cloud-project/
├── app/                     # Application météo (Flask) — Partie 1.4 (SaaS)
├── infra/
│   └── local.conf           # Configuration DevStack utilisée
├── terraform/                # Partie 2 — provisioning VM (à venir)
├── jenkins/                  # Partie 4 — Jenkinsfile (à venir)
├── ansible/                   # Partie 5 — playbooks (à venir)
├── monitoring/                # Partie 3 — script de supervision SLA (à venir)
└── docs/
    ├── openstack-runbook.md   # Procédure de réinstallation DevStack
    └── screenshots/
        └── partie1/           # Captures d'écran Partie 1
```

---

## Partie 1 — Déploiement et utilisation d’OpenStack

**Statut : implémentation terminée** — captures d’écran en cours de finalisation.

### 1.1 Installation d’OpenStack avec DevStack

- **Hôte :** Windows 11 + VirtualBox
- **VM DevStack :** Ubuntu Server 24.04 — 8 Go RAM, 60 Go disque, 4 vCPU
- **Configuration réseau :** carte 1 en pont/NAT Réseau, carte 2 en réseau host-only avec IP statique `192.168.56.10`
- Utilisateur `stack` créé via le script officiel `create-stack-user.sh`
- Configuration DevStack utilisée : [`infra/local.conf`](./infra/local.conf)

**Difficultés rencontrées et résolutions apportées :**

| Problème | Cause | Résolution |
| --- | --- | --- |
| Virtualisation imbriquée non disponible | VT-x/AMD-V nested désactivé au niveau de l’hyperviseur | `VBoxManage modifyvm "VM" --nested-hw-virt on` |
| `su: user stack does not exist` | Compte `openstack` créé à la place du compte `stack` requis par DevStack | Création du compte via le script officiel `create-stack-user.sh` |
| Blocage de l’installation lié aux permissions | Absence du droit d’exécution (`x`) pour “other” sur `/opt/stack`, `/opt/stack/data` et `/opt/stack/data/venv` | Correctif appliqué via `.bashrc` et `/etc/rc.local` (détaillé dans `docs/openstack-runbook.md`) |
| `The q-agt/neutron-agt service must be disabled with OVN` | Les versions récentes de DevStack activent OVN par défaut, incompatible avec l’agent Neutron classique | Utilisation de la configuration DevStack par défaut (sans forçage OVS), stable pour ce projet |
| `apt update` en échec (`Temporary failure resolving...`) sur la VM applicative | Absence de serveur DNS sur le sous-réseau privé Neutron | `openstack subnet set --dns-nameserver 8.8.8.8 --dns-nameserver 1.1.1.1 <subnet-id>` suivi d’un redémarrage de l’instance |

La procédure détaillée et reproductible est documentée dans [`docs/openstack-runbook.md`](./docs/openstack-runbook.md).

### 1.2 Test des services OpenStack

- Dashboard Horizon accessible sur `http://192.168.56.10/dashboard`
- Validation des services via CLI :

```bash
source ~/devstack/openrc admin admin
openstack compute service list
openstack network agent list
openstack image list
```

Nova, Neutron et Keystone sont opérationnels (services à l’état `up`).

### 1.3 Infrastructure as a Service (IaaS) — Instance CirrOS

```bash
ssh-keygen -t rsa -b 2048 -f ~/.ssh/mykey -N ""
openstack keypair create --public-key ~/.ssh/mykey.pub mykey
openstack security group create web-sg
openstack security group rule create --proto tcp --dst-port 22 web-sg
openstack server create --flavor m1.tiny --image cirros-0.6.3-x86_64-disk \
  --network private --key-name mykey --security-group web-sg cirros-vm
openstack floating ip create public
openstack server add floating ip cirros-vm <IP_FLOTTANTE>
ssh -i ~/.ssh/mykey cirros@<IP_FLOTTANTE>
```

Instance déployée, accessible en SSH, avec exécution de commandes Linux de base validée.

### 1.4 Software as a Service (SaaS) — Application météo

**Fonctionnalités de l’application** (`app/`) :

- Recherche de ville, météo courante, courbe horaire sur 24h, prévisions sur 7 jours
- Interface adaptative (fond dynamique selon météo/heure), bascule °C/°F
- Point de contrôle `/health`, destiné à une utilisation future par Jenkins, Ansible et la supervision SLA
- Données fournies par l’API publique Open-Meteo (sans clé d’authentification)

**Déploiement :**

```bash
openstack server create --flavor m1.small --image ubuntu-24.04 \
  --network private --key-name mykey --security-group web-sg ubuntu-web
openstack security group rule create --proto tcp --dst-port 5000 web-sg
openstack server add floating ip ubuntu-web <IP_FLOTTANTE>
```

Sur l’instance `ubuntu-web` :

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv
cd ~/app
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
gunicorn -b 0.0.0.0:5000 app:app
```

**Mise en service permanente (systemd) :**

```bash
sudo systemctl enable --now webapp
sudo systemctl status webapp
```

Image Glance utilisée : `ubuntu-24.04-minimal`, choisie pour sa taille réduite afin d’éviter les interruptions de transfert (`IncompleteRead`) observées avec l’image standard (~625 Mo).

**Capture disponible :** [`docs/screenshots/partie1/meteo-app-navigateur.png`](./docs/screenshots/partie1/meteo-app-navigateur.png) — application accessible depuis le navigateur.

> **À compléter :** captures de Horizon, des services OpenStack (1.2), de l’instance CirrOS et de la connexion SSH (1.3), ainsi que du endpoint `/health` et du statut `systemctl` (1.4).
> 

---

## 🔜 Prochaines parties

- [ ]  **Partie 2** — Terraform (provisioning VM CentOS via provider OpenStack)
- [ ]  **Partie 3** — Script Python de supervision SLA (`sla.json`, `sla_monitor.py`)
- [ ]  **Partie 4** — Pipeline Jenkins (Checkout → Terraform → Ansible → Test → Report)
- [ ]  **Partie 5** — Playbooks Ansible (déploiement app + supervision SLA)

---

## 📚 Documentation complémentaire

Voir [`docs/openstack-runbook.md`](./docs/openstack-runbook.md) pour la procédure complète et détaillée de réinstallation de DevStack sur une nouvelle VM (10 sections, incluant tous les correctifs rencontrés).