// Infrastructure for the scale run: a VM, two managed disks, a virtual
// network, storage, a managed identity, and optionally a registry.
//
// This line said "storage, a registry, and nothing else" -- written before the
// scale run, and left in place after this template grew the VM and disks that
// account for almost all of the cost. The first line of an infrastructure
// file is the one a reader trusts to know what it bills for.
//
// WHY BICEP AND NOT TERRAFORM
//     Terraform needs a state file, which needs a storage account, which needs
//     to exist before the thing that creates storage accounts. That bootstrap
//     is a real cost when the whole deployment lives for one afternoon. Bicep
//     has no state -- Azure Resource Manager is the state -- so `what-if`,
//     deploy, and delete are three commands with nothing to lose track of.
//
// WHY EVERYTHING IS IN ONE RESOURCE GROUP
//     Deleting the resource group is the only reliable way to stop the meter.
//     Azure budget alerts NOTIFY, they do not stop spend, and they lag 8-24
//     hours. So the kill switch has to be structural: one group, one delete,
//     nothing billable outside it.
//
//     ⚠️ Azure Cloud Shell creates its own `cloud-shell-storage-<region>`
//     resource group the first time it is opened. It is OUTSIDE this template
//     and survives deleting this group. Delete it separately, or use an
//     ephemeral Cloud Shell session.
//
// WHAT IS DELIBERATELY ABSENT
//     No Azure ML workspace: it drags in Key Vault, Application Insights and a
//     registry of its own, and its compute needs a vCPU quota that is zero on
//     a trial subscription. This is a single-node DuckDB job; it wants a
//     machine, not an ML platform.
//
//     No spot instances: ACI Spot is preview, is documented as not for
//     production, and trial subscriptions cannot obtain the quota. It would
//     save cents and add a hard-failure path.
//
// Deploy:
//     az group create -n aml-rg -l eastus
//     az deployment group what-if -g aml-rg -f infra/main.bicep
//     az deployment group create  -g aml-rg -f infra/main.bicep
// Destroy (this is the brake):
//     az group delete -n aml-rg --yes --no-wait

@description('Short suffix to keep globally-unique names unique.')
param suffix string = uniqueString(resourceGroup().id)

@description('Region. Storage and compute MUST match, or cross-region egress is billed per GB.')
param location string = resourceGroup().location

var storageName = 'amlstore${take(suffix, 12)}'
var registryName = 'amlacr${take(suffix, 12)}'

// ---------------------------------------------------------------------------
// Storage: ADLS Gen2, hot tier, one container
// ---------------------------------------------------------------------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: {
    // LRS, not GRS. Geo-redundancy doubles the price to protect a dataset that
    // is a free public download and is reproducible from the pipeline anyway.
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    // Hierarchical namespace = real directories. Required for abfss:// and for
    // the partitioned Parquet layout DuckDB writes. It is also why io.ensure_dir
    // must actually create directories rather than no-op on URIs.
    isHnsEnabled: true
    // Hot ONLY. Cool and Cold add per-GB READ charges plus a 30/90-day early
    // deletion penalty -- on a deployment that is torn down the same day, the
    // "cheaper" tiers are strictly more expensive.
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    // Key-based access is DISABLED on purpose. Every credential in this project
    // is an identity, never a secret: `az login` locally, managed identity in
    // the cloud. With this false, an account key cannot be used even if one
    // leaked, and DuckDB's credential_chain is forced down the identity path.
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource dataContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'aml'
  properties: {
    publicAccess: 'None'
  }
}

// ---------------------------------------------------------------------------
// Container registry -- OPTIONAL, and off by default
// ---------------------------------------------------------------------------
// Basic tier, $0.00694/hour. The plan was `az acr build`, which compiles the
// image SERVER-SIDE on amd64 -- the point being that the development laptop is
// arm64 and had no Docker.
//
// IT WAS NEVER USED. Trial subscriptions cannot run ACR Tasks; `az acr build`
// returns TasksOperationsNotAllowed. The image is built two other ways
// instead: by GitHub Actions into GHCR (the published one), and directly on
// the VM with `docker build` from a sha256-verified source tarball (how the
// HI-Large run was actually done). Three registry paths, one of them dead, is
// exactly the divergence an audit flags -- so it is now off unless asked for,
// and the reason is here rather than in a commit message.
//
// Deploying it anyway cost $0.35 across the whole project. The problem was
// never the money; it was that `infra/main.bicep` described an image flow that
// did not exist.
@description('Deploy a container registry. Not needed on a trial subscription: ACR Tasks are blocked there, and the image is built by CI into GHCR or on the VM.')
param deployRegistry bool = false

resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = if (deployRegistry) {
  name: registryName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false   // identity-based pulls only, same rule as storage
  }
}

// ---------------------------------------------------------------------------
// Identity used by the compute that runs the pipeline
// ---------------------------------------------------------------------------
// User-assigned, so the role assignments below can be made and can FINISH
// PROPAGATING before any compute exists. RBAC propagation takes up to 30
// minutes; creating the identity with the job means the job's first blob read
// races the assignment and fails with a 403 that looks like a config error.
//
// ⚠️ DuckDB's `credential_chain` resolves managed identity through IMDS and has
// no way to name WHICH user-assigned identity to use. Set AZURE_CLIENT_ID on
// the container to this identity's clientId, or the chain picks wrongly.
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'aml-job-identity'
  location: location
}

var storageBlobDataContributor = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
var acrPull = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d')

// Scoped to the resource group, never the subscription. A least-privilege
// habit that costs nothing here and is the difference between a mistake that
// affects one afternoon's resources and one that affects an account.
resource blobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, identity.id, storageBlobDataContributor)
  scope: storage
  properties: {
    roleDefinitionId: storageBlobDataContributor
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource acrRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployRegistry) {
  name: guid(resourceGroup().id, identity.id, acrPull)
  scope: registry
  properties: {
    roleDefinitionId: acrPull
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}


// ---------------------------------------------------------------------------
// Compute
// ---------------------------------------------------------------------------
// A plain VM, deliberately. Azure ML was tried and rejected: it drags in Key
// Vault, Application Insights and a registry of its own, and its compute needs
// a dedicated vCPU quota that is ZERO on a trial subscription. This is a
// single-node DuckDB + scikit-learn job. It wants a machine, not a platform.
//
// Standard_E4ds_v7 is not a preference, it is what is available:
//   * regional quota is 4 vCPU total, and 4 per family. Nothing larger exists
//     for this subscription, and `az quota update` returns
//     ResourceNotAvailableForOffer -- a trial cannot raise it.
//   * E4ds_v4, _v5 and _v6 all report NotAvailableForSubscription in eastus.
//     _v7 is the one that provisions.
//   * the E (memory-optimised) family gives 31 GB rather than D's 16 GB, and
//     31 GB is already the binding constraint on the HI-Large fit.
//   * the "d" suffix is the point: a local NVMe resource disk, which is where
//     DuckDB spills. Without it the feature stage writes to the OS disk.
@description('VM size. Constrained by quota, not by preference -- see comment.')
param vmSize string = 'Standard_E4ds_v7'

@description('Admin username. Login is by SSH key; no password is ever set.')
param adminUsername string = 'amladmin'

@description('SSH public key. Optional: all orchestration uses az vm run-command, which needs no inbound port at all.')
param sshPublicKey string = ''

var vmName = 'aml-vm'

resource natIp 'Microsoft.Network/publicIPAddresses@2023-09-01' = {
  name: '${vmName}-outbound-ip'
  location: location
  sku: { name: 'Standard' }
  properties: { publicIPAllocationMethod: 'Static' }
}

resource natgw 'Microsoft.Network/natGateways@2023-09-01' = {
  name: '${vmName}-nat'
  location: location
  sku: { name: 'Standard' }
  properties: { publicIpAddresses: [ { id: natIp.id } ] }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-09-01' = {
  name: '${vmName}-vnet'
  location: location
  properties: {
    addressSpace: { addressPrefixes: ['10.0.0.0/16'] }
    subnets: [ {
      name: 'default'
      properties: {
        addressPrefix: '10.0.0.0/24'
        // ASSOCIATED, not merely provisioned. The NAT gateway below existed
        // without this line: billable, and doing nothing, while the comments
        // claimed outbound went through it. NAT operates at subnet scope and
        // has no effect until a subnet references it.
        natGateway: { id: natgw.id }
        defaultOutboundAccess: false
      }
    } ]
  }
}

// No inbound rules. Every command in this project reaches the VM through
// `az vm run-command`, which goes via the Azure control plane and the guest
// agent -- so there is no open SSH port, and no key to leak, by construction.
resource nsg 'Microsoft.Network/networkSecurityGroups@2023-09-01' = {
  name: '${vmName}-nsg'
  location: location
  properties: { securityRules: [] }
}

// Outbound only: the VM pulls base images and Python wheels. No public IP is
// attached, so nothing can reach it from the internet.
resource nic 'Microsoft.Network/networkInterfaces@2023-09-01' = {
  name: '${vmName}-nic'
  location: location
  properties: {
    networkSecurityGroup: { id: nsg.id }
    ipConfigurations: [ {
      name: 'ipconfig1'
      properties: {
        subnet: { id: '${vnet.id}/subnets/default' }
        privateIPAllocationMethod: 'Dynamic'
      }
    } ]
  }
}

// Spill disk. The feature stage is an unbounded-frame window pass over 2x180M
// account-events and spilled 96 GB; the local NVMe also holds the raw CSV and
// every intermediate, and ran out at 216 GB. This separates the two so a spill
// cannot fill the disk the outputs are being written to.
//
// It is also PERSISTENT, unlike the NVMe resource disk, which Azure wipes on
// deallocate -- stopping the VM to save money destroyed 91 GB of work once.
resource spillDisk 'Microsoft.Compute/disks@2023-10-02' = {
  name: 'aml-spill'
  location: location
  sku: { name: 'StandardSSD_LRS' }
  properties: { creationData: { createOption: 'Empty' }, diskSizeGB: 1024 }
}

resource vm 'Microsoft.Compute/virtualMachines@2023-09-01' = {
  name: vmName
  location: location
  identity: {
    // Both, and for different reasons. The user-assigned identity carries the
    // role assignments and can be created before any compute, so RBAC has time
    // to propagate. The system-assigned one makes the IMDS default
    // unambiguous, which matters because DuckDB's credential_chain resolves
    // managed identity through IMDS with no way to name which one it wants.
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    hardwareProfile: { vmSize: vmSize }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: '0001-com-ubuntu-server-jammy'
        sku: '22_04-lts-gen2'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        diskSizeGB: 64
        managedDisk: { storageAccountType: 'StandardSSD_LRS' }
        deleteOption: 'Delete'
      }
      dataDisks: [ {
        lun: 0
        createOption: 'Attach'
        managedDisk: { id: spillDisk.id }
        deleteOption: 'Detach'
      } ]
    }
    osProfile: {
      computerName: vmName
      adminUsername: adminUsername
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: empty(sshPublicKey) ? null : {
          publicKeys: [ {
            path: '/home/${adminUsername}/.ssh/authorized_keys'
            keyData: sshPublicKey
          } ]
        }
        provisionVMAgent: true       // required by az vm run-command
      }
    }
    networkProfile: { networkInterfaces: [ { id: nic.id, properties: { deleteOption: 'Delete' } } ] }
  }
}

// The VM's SYSTEM-assigned identity also needs blob access. Assigned here
// rather than by hand: doing it manually after the fact is how the first run
// hit "Failed to get token from ChainedTokenCredential" on a half-propagated
// role.
resource vmBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, vm.id, storageBlobDataContributor)
  scope: storage
  properties: {
    roleDefinitionId: storageBlobDataContributor
    principalId: vm.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Outputs: everything the run command needs, and no secrets among them
// ---------------------------------------------------------------------------
output storageAccount string = storage.name
output dataUri string = 'abfss://aml@${storage.name}.dfs.core.windows.net'
output registryLoginServer string = deployRegistry ? registry!.properties.loginServer : ''
output identityClientId string = identity.properties.clientId
output identityResourceId string = identity.id

output vmName string = vm.name
output spillDiskName string = spillDisk.name
