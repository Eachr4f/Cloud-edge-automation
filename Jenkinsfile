// Jenkinsfile - Pipeline de deploiement OpenStack (Partie 4)
// Commit Git -> Terraform (VM) -> Ansible (application) -> Test -> Rapport SLA

pipeline {
  agent any

  options {
    timeout(time: 45, unit: 'MINUTES')
    disableConcurrentBuilds()
  }

  // Un commit sur GitHub declenche le pipeline (verification toutes les ~2 minutes)
  triggers {
    pollSCM('H/2 * * * *')
  }

  environment {
    OS_AUTH_URL        = 'http://192.168.56.10/identity'
    OS_USERNAME        = 'admin'
    OS_PASSWORD        = credentials('openstack-pass')
    TF_VAR_os_password = credentials('openstack-pass')
    TF_IN_AUTOMATION   = 'true'
    TF_STATE           = "${JENKINS_HOME}/tfstate/webapp.tfstate"
  }

  stages {

    stage('Checkout') {
      steps {
        checkout scm
        sh 'git log -1 --pretty=format:"%h %s (%an)"'
      }
    }

    stage('Validate') {
      steps {
        sh '''
          python3 -c "import ast; ast.parse(open('app/app.py').read())"
          python3 -c "import json; json.load(open('monitoring/sla.json'))"
          ansible-playbook -i localhost, --syntax-check ansible/playbook.yml
        '''
        dir('terraform/webapp') {
          sh '''
            terraform init -backend=false -input=false
            terraform validate
          '''
        }
      }
    }

    stage('Terraform Init & Plan') {
      steps {
        dir('terraform/webapp') {
          sh '''
            mkdir -p "$(dirname "$TF_STATE")"
            terraform init -input=false -reconfigure -backend-config="path=$TF_STATE"
            terraform plan -input=false -out=tfplan
          '''
        }
      }
    }

    stage('Terraform Apply') {
      steps {
        dir('terraform/webapp') {
          sh 'terraform apply -input=false tfplan'
          script {
            env.VM_IP = sh(script: 'terraform output -raw floating_ip', returnStdout: true).trim()
          }
        }
        echo "VM deployee : ${env.VM_IP}"
      }
    }

    stage('Ansible Provision') {
      steps {
        writeFile file: 'ansible/inventory.ini',
                  text: "[openstack_vms]\nwebapp-vm ansible_host=${env.VM_IP} ansible_user=ubuntu\n\n[openstack_vms:vars]\nansible_python_interpreter=/usr/bin/python3\n"
        sshagent(credentials: ['ssh-key-openstack']) {
          sh 'ANSIBLE_HOST_KEY_CHECKING=False ansible-playbook -i ansible/inventory.ini ansible/playbook.yml'
        }
      }
    }

    stage('Test') {
      steps {
        sh '''
          curl -fsS --retry 12 --retry-delay 5 --retry-connrefused --max-time 10 "http://${VM_IP}:5000/health"
          echo
          curl -fsS --max-time 20 -o /dev/null "http://${VM_IP}:5000/"
          echo "Application accessible : http://${VM_IP}:5000"
        '''
      }
    }

    stage('Report') {
      steps {
        sh '''
          mkdir -p reports
          {
            echo "=== Rapport de deploiement Jenkins ==="
            echo "Build        : #${BUILD_NUMBER}"
            echo "Date (UTC)   : $(date -u +%Y-%m-%dT%H:%M:%SZ)"
            echo "Commit       : $(git rev-parse --short HEAD)"
            echo "VM           : webapp-vm (${VM_IP})"
            echo "Application  : http://${VM_IP}:5000"
            echo "Health       : $(curl -s --max-time 10 http://${VM_IP}:5000/health)"
            echo ""
          } > reports/deploy_report_${BUILD_NUMBER}.txt
        '''
        script {
          // Mise a jour du SLA : 0 = respecte, 2 = viole (build "instable"), autre = erreur
          def rc = sh(script: 'python3 monitoring/sla_monitor.py', returnStatus: true)
          sh 'python3 monitoring/sla_monitor.py --report-only >> reports/deploy_report_${BUILD_NUMBER}.txt || true'
          if (rc == 2) {
            unstable('Objectif SLA non respecte - voir le rapport archive')
          } else if (rc != 0) {
            error("sla_monitor.py a echoue (code ${rc})")
          }
        }
      }
    }
  }

  post {
    failure {
      sh '''
        mkdir -p reports
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) Pipeline #${BUILD_NUMBER} en echec - violation SLA journalisee" >> reports/alerts.log
      '''
      echo 'Pipeline failed - SLA violation logged'
    }
    success {
      echo "Deploiement reussi : http://${env.VM_IP}:5000"
    }
    cleanup {
      archiveArtifacts artifacts: 'reports/**,monitoring/reports/**', allowEmptyArchive: true
    }
  }
}
