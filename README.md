# xApp for Monitoring

## Contact

For help and information regarding this project, please contact: Dimitrios.Kefalas@lip6.fr

## Overview

In this project, you are tasked with deploying a fully operational 5G network with a RIC using OpenAirInterface (OAI) and Kubernetes. By utilizing Kubernetes, the different network functions will run as independent Docker containers within a microservices environment provided by Kubernetes. 

The goal of the project is to develop and deploy an xApp that leverages the KPM (Key Performance Measurement) service model within FlexRIC to monitor and analyze various performance metrics in a cloud-based 5G environment. The project involves executing experiments to collect performance data and build a corresponding dataset.

---

## Objective
- Utilize the KPM service model within FlexRIC to monitor and observe different KPM metrics.
- Execute multiple experiments and create a dataset with the corresponding metrics.

---

## Tools & Software
- Kubernetes
- OpenAirInterface5G CN and RAN
- FlexRIC (cloud-based)

---

## Getting Started

### Step 1: Clone the Repository
Clone the repository to your VMs.

---

### Step 2: Verify Your Kubernetes Environment
Check if you already have a healthy Kubernetes environment:

- If your Kubernetes setup is functional, proceed to the Ansible installation section.
- If you do not have a healthy Kubernetes environment, move to the next step.

---

### Step 3: Setting Up Kubernetes
Navigate to the `kubernetes-setup` folder in the repository.

This folder contains Ansible playbooks for:
- Uninstalling any existing Kubernetes setup.
- Installing a fresh Kubernetes environment.
- Setting up a cluster, including:
  - The control plane node.
  - Worker nodes that will join the cluster.

Follow the instructions in the `kubernetes-setup` folder to set up your Kubernetes environment.

---

### Step 4: Proceed to Ansible Installation
Once your Kubernetes environment is set up, you can proceed with the installation using the provided Ansible playbooks.

Begin by updating the inventories/UTH/hosts.yml file with the correct IPs and node names corresponding to your VMs.

Next, modify the inventories/UTH/group_vars/all file to include the appropriate ansible_user value.

After completing these steps, you can proceed with deploying the scenario by executing the following command:
```bash
ansible-playbook -i inventories/UTH 5g.yaml --extra-vars "@params.oai-flexric.yaml"
```
If everything has been set up correctly, you should be able to ping from your UE to the 5GCN. To do this, execute a command to ping the 5GCN from your UE. 
```bash
kubectl exec -ti oai-nr-ue-7dbdb954fc-4rbn4 -n blueprint -- ping 12.1.1.1
```


**Note**: The pod name in the command above is an example and will likely differ in your setup. Use `kubectl get pods` to find the correct pod name.

---

## Deploying a Monitoring xApp

The next step is to create and deploy a monitoring xApp. To deploy your xApp, run the following commands on the deployment host (master):
```bash
kubectl exec -ti oai-flexric-5db68d7bf6-n28q8 bash -n blueprint
```

This will connect you to the RIC environment, where you can choose the programming language for your xApp (C or Python3):

- For **C language**: Navigate to `/flexric/build/examples/xApp/c`
- For **Python3**: Navigate to `/flexric/build/examples/xApp/python3`

**Example**: To run an xApp that monitors KPM metrics for the RAN, use the following command:

```bash
./xapp_kpm_moni
```

## Configuration Files and Directories

You can view or edit configuration files for the Core, RAN, FlexRIC, and UE in the following directories:

- **Core Files**:  
  `blueprint/sopnode/ansible/roles/flexric/files/blueprint/oai-flexric/core_files`

- **Core Configurations**:  
  `blueprint/sopnode/ansible/roles/flexric/files/blueprint/oai-flexric/core_values`

- **RAN Files**:  
  `blueprint/sopnode/ansible/roles/flexric/files/blueprint/oai-flexric/ran_files`

- **RAN Configurations**:  
  `blueprint/sopnode/ansible/roles/flexric/files/blueprint/oai-flexric/ran_values`

- **FlexRIC Files**:  
  `blueprint/sopnode/ansible/roles/flexric/files/blueprint/oai-flexric/flexric_files`

- **FlexRIC Configurations**:  
  `blueprint/sopnode/ansible/roles/flexric/files/blueprint/oai-flexric/flexric_values`

- **UE Files**:  
  `blueprint/sopnode/ansible/roles/flexric/files/blueprint/oai-flexric/ue_files`

- **UE Configurations**:  
  `blueprint/sopnode/ansible/roles/flexric/files/blueprint/oai-flexric/ue_values`

---

## Uninstalling the Previous Deployment

To uninstall the previous deployment (OAI Core, RF Simulator, FlexRIC, and UE), run the following Ansible playbook:

ansible-playbook -i inventories/UTH destroy-oai-flexric.yaml


This playbook will cleanly remove all components of the blueprint deployment.

---

## Project Goals
The primary goal of this project is to develop and deploy an xApp that:
- Leverages the KPM service model within FlexRIC.
- Monitors and observes various performance metrics in a cloud-based 5G environment.
- Collects data through experiments and creates a dataset for further analysis.

This project uses:
- Kubernetes for orchestration.
- OpenAirInterface5G for Core Network (CN) and Radio Access Network (RAN).
- FlexRIC for RIC-based monitoring and control.

