# Projet Cloud & Edge Computing — Intégration Jenkins & Ansible

*Réalisé par Achraf — Module Cloud et Edge Computing, encadré par Prof. C. EL AMRANI.*

## Environnement de travail

L'ensemble du projet est réalisé en local, sans recours à une plateforme Cloud externe :

- **Machine hôte :** PC Windows 11 avec VirtualBox comme hyperviseur (virtualisation imbriquée activée).
- **Plateforme Cloud :** OpenStack déployé avec DevStack dans une VM Ubuntu Server 24.04 (8 Go de RAM, 4 vCPU, 60 Go de disque). La VM dispose de deux cartes réseau : une carte d'accès à Internet et une carte host-only à l'IP statique `192.168.56.10`, qui donne accès à l'API et à Horizon depuis Windows.
- **Services OpenStack utilisés :** Keystone (identité), Glance (images), Nova (compute), Neutron (réseau) et Horizon (tableau de bord).
- **Machines invitées :** `cirros-vm` (CirrOS), `ubuntu-web` (Ubuntu 24.04, application météo Flask) et `centos-terraform` (CentOS Stream, déployée avec Terraform).
- **Outils côté poste Windows :** Terraform 1.16, Git et PowerShell. Jenkins et Ansible seront ajoutés dans les parties 4 et 5.

## Présentation

Ce dépôt regroupe l'implémentation du projet en cinq parties : déploiement OpenStack (DevStack), provisioning d'infrastructure avec Terraform, supervision SLA, automatisation CI/CD avec Jenkins, et gestion de configuration avec Ansible. L'ensemble de l'infrastructure est déployé localement via VirtualBox, conformément aux consignes du projet.

---

## Structure du dépôt

```
cloud-project/
├── app/                      # Application météo (Flask) — Partie 1.4 (SaaS)
├── tests/                    # Tests de l'application
├── infra/
│   └── local.conf            # Configuration DevStack utilisée
├── terraform/                # Partie 2 — provisioning de la VM CentOS
│   ├── versions.tf           # Version de Terraform et du provider OpenStack
│   ├── provider.tf           # Connexion à l'API OpenStack
│   ├── variables.tf          # Variables (mot de passe fourni hors fichier)
│   ├── main.tf               # Instance, IP flottante, association
│   └── outputs.tf            # Sorties (ID, état, IP flottante)
├── jenkins/                  # Partie 4 — Jenkinsfile (à venir)
├── ansible/                  # Partie 5 — playbooks (à venir)
├── monitoring/               # Partie 3 — supervision SLA
│   ├── sla.json              # Définition du SLA (objectifs, métriques, seuils)
│   ├── sla_monitor.py        # Script de supervision (bibliothèque standard uniquement)
│   └── sla.env.example       # Modèle des identifiants (le vrai sla.env n'est pas versionné)
└── docs/
    ├── openstack-runbook.md  # Procédure de réinstallation DevStack
    └── screenshots/
        ├── partie1/          # Captures d'écran Partie 1
        ├── partie2/          # Captures d'écran Partie 2
        └── partie3/          # Captures d'écran Partie 3
```

---

## Partie 1 — Déploiement et utilisation d'OpenStack

**Statut : implémentation terminée** — captures d'écran en cours de finalisation.

### 1.1 Installation d'OpenStack avec DevStack

- **Hôte :** Windows 11 + VirtualBox
- **VM DevStack :** Ubuntu Server 24.04 — 8 Go RAM, 60 Go disque, 4 vCPU
- **Configuration réseau :** carte 1 en pont/NAT Réseau, carte 2 en réseau host-only avec IP statique `192.168.56.10`
- Utilisateur `stack` créé via le script officiel `create-stack-user.sh`
- Configuration DevStack utilisée : [`infra/local.conf`](./infra/local.conf)

**Difficultés rencontrées et résolutions apportées :**

| Problème | Cause | Résolution |
|---|---|---|
| Virtualisation imbriquée non disponible | VT-x/AMD-V nested désactivé au niveau de l'hyperviseur | `VBoxManage modifyvm "VM" --nested-hw-virt on` |
| `su: user stack does not exist` | Compte `openstack` créé à la place du compte `stack` requis par DevStack | Création du compte via le script officiel `create-stack-user.sh` |
| Blocage de l'installation lié aux permissions | Absence du droit d'exécution (`x`) pour "other" sur `/opt/stack`, `/opt/stack/data` et `/opt/stack/data/venv` | Correctif appliqué via `.bashrc` et `/etc/rc.local` (détaillé dans `docs/openstack-runbook.md`) |
| `The q-agt/neutron-agt service must be disabled with OVN` | Les versions récentes de DevStack activent OVN par défaut, incompatible avec l'agent Neutron classique | Utilisation de la configuration DevStack par défaut (sans forçage OVS), stable pour ce projet |
| `apt update` en échec (`Temporary failure resolving...`) sur la VM applicative | Absence de serveur DNS sur le sous-réseau privé Neutron | `openstack subnet set --dns-nameserver 8.8.8.8 --dns-nameserver 1.1.1.1 <subnet-id>` suivi d'un redémarrage de l'instance |

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
Nova, Neutron et Keystone sont opérationnels (services à l'état `up`).

**Capture :** [`docs/screenshots/partie1/instances-actives.png`](./docs/screenshots/partie1/instances-actives.png) — vue Horizon des instances `ubuntu-web` et `cirros-vm`, toutes deux à l'état `Active`.

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
Instance déployée, accessible en SSH, avec exécution de commandes Linux de base validée (voir capture des instances ci-dessus pour l'état `Active` de `cirros-vm`).

### 1.4 Software as a Service (SaaS) — Application météo

**Fonctionnalités de l'application** (`app/`) :
- Recherche de ville, météo courante, courbe horaire sur 24h, prévisions sur 7 jours
- Interface adaptative (fond dynamique selon météo/heure), bascule °C/°F
- Point de contrôle `/health`, destiné à une utilisation future par Jenkins, Ansible et la supervision SLA
- Données fournies par l'API publique Open-Meteo (sans clé d'authentification)

**Déploiement :**
```bash
openstack server create --flavor m1.small --image ubuntu-24.04 \
  --network private --key-name mykey --security-group web-sg ubuntu-web
openstack security group rule create --proto tcp --dst-port 5000 web-sg
openstack server add floating ip ubuntu-web <IP_FLOTTANTE>
```

Sur l'instance `ubuntu-web` :
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

Image Glance utilisée : `ubuntu-24.04-minimal`, choisie pour sa taille réduite afin d'éviter les interruptions de transfert (`IncompleteRead`) observées avec l'image standard (~625 Mo).

**Captures disponibles :**
- [`docs/screenshots/partie1/meteo-app-navigateur.png`](./docs/screenshots/partie1/meteo-app-navigateur.png) — application accessible depuis le navigateur
- [`docs/screenshots/partie1/health-endpoint.png`](./docs/screenshots/partie1/health-endpoint.png) — réponse du point de contrôle `/health` (`status: ok`)
- [`docs/screenshots/partie1/systemctl-status-webapp.png`](./docs/screenshots/partie1/systemctl-status-webapp.png) — service `webapp.service` à l'état `active (running)`

> **À compléter :** capture du dashboard Horizon (connexion) et des sorties CLI de la section 1.2 (`compute service list`, `network agent list`).

---

## Partie 2 — Infrastructure as Code avec Terraform

**Statut : terminée.**

### 2.1 Installation et configuration de Terraform

Terraform 1.16 est installé sur le poste Windows via `winget` :

```powershell
winget install HashiCorp.Terraform
terraform -version
```

Le provider OpenStack (`terraform-provider-openstack/openstack`, version `~> 1.53.0`) pointe vers l'API Keystone de la DevStack locale : `http://192.168.56.10/identity/v3`.

Le code est réparti dans cinq fichiers du dossier [`terraform/`](./terraform) :

| Fichier | Rôle |
|---|---|
| `versions.tf` | Version minimale de Terraform et version du provider |
| `provider.tf` | Paramètres de connexion à OpenStack |
| `variables.tf` | Variables : URL d'authentification, projet, clé SSH, réseau, groupe de sécurité |
| `main.tf` | Instance CentOS, IP flottante et son association |
| `outputs.tf` | Sorties : identifiant, état et IP flottante de l'instance |

**Gestion du mot de passe.** Le mot de passe administrateur n'est écrit dans aucun fichier versionné. Il est fourni par une variable d'environnement, et la variable Terraform correspondante est marquée `sensitive` :

```powershell
$env:TF_VAR_os_password = "<mot de passe admin>"
```

Le `.gitignore` exclut `.terraform/`, les fichiers `*.tfstate*` et `terraform.tfvars`.

### 2.2 Déploiement d'une VM CentOS

**Préparation sur la VM DevStack.** L'image CentOS Stream est importée dans Glance sous le nom `CentOS-Terraform`, et une flavor adaptée est créée. CentOS Stream demande environ 1,5 Go de RAM et 10 Go de disque au minimum, ce que les flavors par défaut ne fournissent pas de façon adaptée :

```bash
openstack image create "CentOS-Terraform" \
  --file /tmp/CentOS-Stream-GenericCloud-9-latest.x86_64.qcow2 \
  --disk-format qcow2 --container-format bare --public
openstack flavor create --ram 2048 --disk 10 --vcpus 1 m1.centos
```

**Ressource principale** (extrait de `main.tf`) :

```hcl
resource "openstack_compute_instance_v2" "centos_vm" {
  name            = "centos-terraform"
  image_name      = "CentOS-Terraform"
  flavor_name     = "m1.centos"
  key_pair        = var.key_pair_name
  security_groups = [var.security_group]

  network {
    name = var.network_name
  }
}
```

**Exécution :**

```powershell
cd terraform
terraform init      # téléchargement du provider
terraform plan      # 3 ressources à créer
terraform apply     # déploiement
terraform show      # état complet
```

**Résultat :**

| Élément | Valeur |
|---|---|
| Instance | `centos-terraform` — état `ACTIVE` |
| Image / flavor | `CentOS-Terraform` / `m1.centos` (2 Go RAM, 10 Go disque, 1 vCPU) |
| Réseau privé | `10.0.0.31` |
| IP flottante | `172.24.4.27` |
| Clé SSH / groupe de sécurité | `mykey` / `web-sg` |
| Utilisateur SSH de l'image | `cloud-user` |

La VM est visible dans Horizon et avec la CLI OpenStack (`openstack server list`).

**Difficulté rencontrée :**

| Problème | Cause | Résolution |
|---|---|---|
| `Error: Unable to find image with name CentOS-Stream-9` | L'image avait été importée dans Glance sous le nom `CentOS-Terraform`, alors que `main.tf` référençait un autre nom | Vérification avec `openstack image list`, puis alignement de `image_name` sur le nom réel de l'image |

**Captures :**

- [`terraform-apply-complete.png`](./docs/screenshots/partie2/terraform-apply-complete.png) — fin de `terraform apply` avec les sorties (`floating_ip`, `instance_id`, `instance_status`)
- [`openstack-server-list.png`](./docs/screenshots/partie2/openstack-server-list.png) — `openstack server list` : `centos-terraform` à l'état `ACTIVE` avec son IP flottante
- [`horizon-instances-centos.png`](./docs/screenshots/partie2/horizon-instances-centos.png) — Horizon : les trois instances à l'état `Active`

> **À compléter :** captures de `terraform init`, de `terraform plan` et de `terraform show`.

---

## Partie 3 — SLA et supervision

**Statut : terminée.**

### 3.1 Définition du SLA

Le fichier [`monitoring/sla.json`](./monitoring/sla.json) décrit l'engagement de service de l'environnement OpenStack :

| Paramètre | Valeur |
|---|---|
| Objectif de disponibilité | 99,5 % |
| Période d'évaluation | journalière |
| Intervalle de mesure | 5 minutes |
| Services surveillés | Keystone, Nova, Neutron (Ceilometer en option) |
| Métriques | disponibilité (uptime), latence réseau, état des instances |
| Seuils d'avertissement | API : 2 000 ms — réseau : 200 ms |

**Définition de la disponibilité.** Un échantillon, pris toutes les 5 minutes, est considéré comme disponible si Keystone, Nova et Neutron répondent correctement et si aucune instance n'est à l'état `ERROR`. La disponibilité du jour est le rapport entre les échantillons disponibles et l'ensemble des échantillons du jour.

**Actions en cas de violation** (`alert_on_violation: true`) : écriture d'une alerte dans `reports/alerts.log`, génération du rapport journalier, et code de sortie `2`, que Jenkins pourra exploiter en Partie 4.

### 3.2 Script Python de surveillance

Le script [`monitoring/sla_monitor.py`](./monitoring/sla_monitor.py) n'utilise que la bibliothèque standard de Python 3, ce qui simplifie son déploiement ultérieur par Ansible. À chaque exécution, il :

1. s'authentifie auprès de Keystone et récupère le catalogue des services ;
2. teste les API Nova (liste des instances), Neutron (état des agents) et Keystone (émission d'un jeton), et mesure leur temps de réponse ;
3. contrôle Ceilometer s'il figure au catalogue ; il n'est pas déployé dans cette DevStack et est donc signalé comme « non déployé » sans provoquer d'erreur ;
4. relève l'état de chaque instance et mesure la latence réseau par une connexion TCP vers son IP flottante ;
5. enregistre l'échantillon dans `data/history.jsonl` ;
6. calcule la disponibilité du jour, la compare à l'objectif et écrit le résultat dans la section `last_report` de `sla.json` ainsi que dans `reports/sla_report_<date>.txt` et `.json`.

Options utiles : `--report-only` (recalcule le rapport sans nouvelle mesure) et `--reset-history` (efface l'historique).

**Identifiants.** Ils sont lus dans un fichier `sla.env` (modèle : `sla.env.example`) exclu de Git, avec des droits `600`.

**Installation sur la VM DevStack (utilisateur `stack`) :**

```bash
sudo mkdir -p /opt/monitoring && sudo chown stack:stack /opt/monitoring
sudo cp -r /tmp/monitoring/. /opt/monitoring/ && sudo chown -R stack:stack /opt/monitoring
cd /opt/monitoring
cp sla.env.example sla.env && chmod 600 sla.env      # renseigner le mot de passe admin
chmod +x sla_monitor.py
python3 sla_monitor.py
```

**Exécution automatique toutes les 5 minutes (crontab de l'utilisateur `stack`) :**

```
*/5 * * * * flock -n /tmp/sla.lock /usr/bin/python3 /opt/monitoring/sla_monitor.py >> /opt/monitoring/sla_monitor.log 2>&1
```

`flock` empêche deux exécutions de se chevaucher : les API de cette DevStack étant lentes, une mesure peut durer plus d'une minute.

### 3.3 Résultats

**Cas nominal.** Après plusieurs exécutions automatiques, le rapport indique 100 % de disponibilité pour Keystone, Nova et Neutron, soit un verdict **« OBJECTIF RESPECTE »** face à l'objectif de 99,5 %. Il montre aussi l'effet d'une instance éteinte volontairement : `cirros-vm`, à l'état `SHUTOFF`, affiche un uptime de 85,71 % (6 échantillons sur 7 à l'état `ACTIVE`), sans que cela constitue une violation, puisque seul l'état `ERROR` rend un échantillon indisponible.

**Test de violation.** Une mesure est volontairement mise en échec avec un mauvais mot de passe :

```bash
OS_PASSWORD=faux python3 sla_monitor.py
echo $?                       # 2
cat reports/alerts.log
python3 sla_monitor.py --report-only
```

La disponibilité du jour passe sous 99,5 %, le verdict devient **« OBJECTIF NON RESPECTE »**, l'alerte est écrite dans `reports/alerts.log` et le script retourne le code `2`. L'historique est ensuite remis à zéro avec `--reset-history`.

**Observation.** Les temps de réponse des API sont élevés, en moyenne plusieurs secondes pour Nova, bien au-dessus du seuil d'avertissement de 2 000 ms. Cela s'explique par les ressources limitées de la VM DevStack, qui s'exécute dans VirtualBox sans accélération matérielle complète. Ce seuil déclenche un avertissement dans le rapport, pas une violation du SLA.

**Difficulté rencontrée :**

| Problème | Cause | Résolution |
|---|---|---|
| Copie de `/tmp/monitoring` impossible en tant que `stack` | Le dossier avait été créé par l'utilisateur `openstack` avec des droits restrictifs, et le joker `*` échoue pour la même raison | `sudo cp -r /tmp/monitoring/. /opt/monitoring/` puis `sudo chown -R stack:stack /opt/monitoring` |

**Captures :**

- [`sla-rapport-respecte.png`](./docs/screenshots/partie3/sla-rapport-respecte.png) — rapport avec le verdict « OBJECTIF RESPECTE »
- [`sla-rapport-violation.png`](./docs/screenshots/partie3/sla-rapport-violation.png) — rapport et alerte lors du test de violation

---

## Prochaines parties

- [x] **Partie 1** — OpenStack (DevStack), IaaS et SaaS
- [x] **Partie 2** — Terraform (provisioning de la VM CentOS via le provider OpenStack)
- [x] **Partie 3** — SLA et script Python de supervision (`sla.json`, `sla_monitor.py`)
- [ ] **Partie 4** — Pipeline Jenkins (Checkout, Terraform, Ansible, Test, Report)
- [ ] **Partie 5** — Playbooks Ansible (déploiement de l'application et supervision SLA)

---

## Documentation complémentaire

Voir [`docs/openstack-runbook.md`](./docs/openstack-runbook.md) pour la procédure complète et détaillée de réinstallation de DevStack sur une nouvelle VM (10 sections, incluant tous les correctifs rencontrés).
