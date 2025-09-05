# MCP Wiki Server on AKS

This project demonstrates end‑to‑end guidelines and implemenation for exposing a Model Context Protocol (MCP) server as a secure, scalable cloud service.
It includes:

* A lightweight Python MCP implementation providing a single tool (`answerQ`) that fetches Wikipedia summaries.
* Local development workflow (uv + Uvicorn), containerization, and production deployment on Azure Kubernetes Service (AKS).
* Automated TLS (Let’s Encrypt via cert-manager) with an NGINX ingress supplied by Azure’s managed Application Routing add-on.
* Integration paths for both GitHub Copilot / VS Code (via `.vscode/mcp.json`) and Azure AI Agent Service (agent consuming an external MCP tool over HTTPS).
* Primary goals: Exploring AI-Assisted development with GitHub Copilot, MCP learning, clarity, simplicity.

## AI-Assisted Development

In this project I'm continuing experimenting with AI-assisted development using GitHub Copilot.

#### Key AI guidance artifacts

- `spec.txt`: Source-of-truth for project scope, functional goals, deployment targets, and non‑functional requirements (e.g., HTTPS, Kubernetes deployment, MCP transport expectations). Conversational prompts were anchored to this spec so generated code stayed aligned.
- `.github/instructions/` (e.g. `kubernetes-deployment-best-practices.instructions.md`): Domain best‑practice scaffolds consumed by GitHub Copilot to ensure manifests include probes, resource limits, non-root security context, TLS considerations, and structured rollout strategies.

## 1. Features

- Single MCP tool: `answerQ`
- Streamable HTTP endpoint (`/mcp/`) with JSON/SSE
- Health endpoint: `/healthz`
- Kubernetes Deployment + Service + Ingress (TLS via Let’s Encrypt)
- VS Code MCP client config and integration with GitHub Copilot
- Agent Service AI Agent Integration with MCP server

## 2. Key Files

- Server: [mcp-wiki/server/server.py](mcp-wiki/server/server.py)
- Dockerfile: [mcp-wiki/server/Dockerfile](mcp-wiki/server/Dockerfile)
- Foundry Agent Service agent script: [mcp-wiki/agent-service/agent_mcp_wiki.py](mcp-wiki/agent-service/agent_mcp_wiki.py)
- K8s manifests: [mcp-wiki/k8s/https](mcp-wiki/k8s/https)
- VS Code MCP config: [.vscode/mcp.json](.vscode/mcp.json)
- Env vars: [.env_template](.env_template)
- spec.txt

## 3. Prerequisites

- Python 3.10+
- uv (https://docs.astral.sh/uv)
- Docker
- Azure CLI (`az`)
- kubectl
- An Azure subscription + ACR + AKS
- (Optional) jq for JSON formatting

Install uv:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 4. Local Setup

```bash
git clone https://github.com/vladfeigin/foundry-agent-service-mcp-demo.git
cd foundry-agent-service-mcp-demo/mcp-wiki
uv sync
uv run uvicorn server.server:starlette_app --host 0.0.0.0 --port 4200
```

MCP Server health check:

```bash
curl -s http://localhost:4200/healthz
```

List MCP server tools (NOTE trailing slash /mcp/):

```bash
curl -sS http://localhost:4200/mcp/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq .
```

Call tool:

```bash
curl -sS http://localhost:4200/mcp/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  --data '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"answerQ","arguments":{"question":"Ada Lovelace"}}}' \
  | jq -r '.result.content[0].text'
```

## 5. Docker

Build and run the Docker image (MCP server) locally:

```bash
docker build -f server/Dockerfile -t mcp-wiki-server .
docker run -p 4200:4200 mcp-wiki-server
```

Now you have an MCP server running locally in a Docker container.

### Connecting to local MCP Server

Integrate the locally running MCP server with GitHub Copilot.
Add to .vscode/mcp.json:

```json
{
  "servers": {
    "wiki-local": {
      "type": "http",
      "url": "http://0.0.0.0:4200/mcp/"
    }
  }
}
```

Start the server.
In GitHub Copilot, Agent Mode, type: "Ada Lovelace" - GitHub Copilot will call the local MCP server.

#### Run MCP inspector

You can also run MCP Inspector:

```bash
npx @modelcontextprotocol/inspector
URL: http://localhost:4200/mcp/
Transport Type: Streamable HTTP
Connect
List Tools
answerQ
```

Great! Now you have a working local MCP server integrated with GitHub Copilot.

## 6. Provision Azure Resources

The MCP server is running locally and integrated with GitHub Copilot. Next, provision the Azure infrastructure needed to deploy it remotely on AKS with HTTPS. You will create a resource group, an Azure Container Registry (ACR) for the image, and an AKS cluster that will host the MCP server.

Change the names, Azure region and other parameters as needed.

Create Resource Group

```bash
az group create -n rg-mcp-wiki-demo-ex -l swedencentral
```

Create Azure Container Registry (ACR):

```bash
az acr create -g rg-mcp-wiki-demo-ex -n mcpwikidemoex --sku Basic --admin-enabled true
```

Create AKS cluster and get credentials:

```bash
az aks create \
  --resource-group rg-mcp-wiki-demo-ex \
  --name aks-mcp-wiki-ex \
  --node-count 2 \
  --node-vm-size Standard_B2s \
  --generate-ssh-keys \
  --attach-acr mcpwikidemoex \
  --enable-managed-identity \
  --network-plugin azure \
  --load-balancer-sku standard \
  --enable-oidc-issuer \
  --enable-workload-identity

az aks get-credentials -g rg-mcp-wiki-demo-ex -n aks-mcp-wiki-ex
```

Login to ACR, build multi-arch container for Linux and push to ACR:

```bash
az acr login -n mcpwikidemoex
docker buildx build \
  --platform linux/amd64 \
  -f server/Dockerfile \
  -t mcpwikidemoex.azurecr.io/mcp-wiki-server:v1.0.1 \
  --push .
```

## 7. Deploy to AKS

Azure Foundry expects your MCP server to be reachable over HTTPS only. So we need to install cert-manager, which provides the CRDs for `clusterissuers.cert-manager.io`.

```bash
helm install cert-manager oci://quay.io/jetstack/charts/cert-manager \
  --version v1.18.2 \
  --namespace cert-manager \
  --create-namespace \
  --set crds.enabled=true
```

Check it was installed  properly:

```bash
kubectl get pods -n cert-manager
kubectl get crd | grep cert-manager.io
```

To receive HTTPS traffic, we need to install Ingress Controller. In this project we use Azure Managed NGINX Ingress
[Nginx Ingress Controller](https://learn.microsoft.com/en-us/azure/aks/app-routing?utm_source=chatgpt.com#enable-application-routing-using-azure-cli "Nginx Ingress")

Enable it on the existing cluster, run:

```bash
az aks approuting enable --resource-group rg-mcp-wiki-demo-ex --name aks-mcp-wiki-ex
```

Before running `kubectl apply` make sure you’ve completed the following changes:

1. Update the image name to the corect ACR image path.
   In [mcp-wiki/k8s/deployment.yaml](mcp-wiki/k8s/deployment.yaml):

   ```yaml
   spec:
     containers:
     - name: mcp-wiki-server
       image: mcpwikidemoex.azurecr.io/mcp-wiki-server:v1.0.1   # <— your image
   ```
2. Find the external IP of the Ingress Controller (managed NGINX ingress controller runs in the `app-routing-system` namespace):

   ```bash
   kubectl get svc -n app-routing-system
   ```
3. Update [mcp-wiki/k8s/ingress.yaml](mcp-wiki/k8s/ingress.yaml):

   Note: This example uses the *wildcard DNS* service **sslip.io** (https://sslip.io/), which maps <IP_ADDRESS>.sslip.io (and hostnames containing it) to the given IP. This is fine for demos; for production use a real domain and DNS.

   Convert the external IP to sslip.io dash notation (replace dots with dashes):
   Example: 1.234.56.78 -> 1-234-56-78

   Pick an HTTPS host name (example prefix: mcp-https):
   mcp-https.1-234-56-78.sslip.io

   Update your Ingress manifest (ingress.yaml) host and TLS entries accordingly:

```
       spec:
        tls:
        - hosts:
          - mcp-https.<DASHED_EXTERNAL_IP>.sslip.io
          secretName: mcp-wiki-tls
        rules:
        - host: mcp-https.<DASHED_EXTERNAL_IP>.sslip.io
          http:
```

Replace `<DASHED_EXTERNAL_IP>` with the dash-formatted external IP (e.g., `1-234-56-78`).

Apply namespace, issuers, deployment, service, ingress:

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/clusterissuer-prod.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml
```

Check all services run as expected:

```bash
kubectl -n mcp-wiki-https get pods
kubectl -n mcp-wiki-https get svc
kubectl -n mcp-wiki-https get ingress
kubectl -n mcp-wiki-https get certificate
```

## 8. HTTPS Validation

```bash
HOST="https://mcp-https.DASHED_EXTERNAL_IP.sslip.io"
curl -sS $HOST/healthz
curl -sS $HOST/mcp/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  --data '{"jsonrpc":"2.0","id":10,"method":"tools/list"}'
```

## 9. VS Code MCP Client

Edit [.vscode/mcp.json](.vscode/mcp.json):

```json
{
  "servers": {
    "wiki-aks-https": {
      "type": "http",
      "url": "https://mcp-https.DASHED_EXTERNAL_IP.sslip.io/mcp/",
      "headers": {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18"
      }
    }
  }
}
```

## 10. Azure AI Agent Service

The next step is to launch the agent in Azure AI Agent Service and set its tools to use the MCP server we deployed on AKS.

Rename .env_template to .env and populate the following parameters:

PROJECT_ENDPOINT="https://`<your-project-endpoint>`"                     # e.g. https://myproj.eastus.models.ai.azure.com
MODEL_DEPLOYMENT_NAME="`<your-model-deployment-name>`"         # e.g. gpt-4o-mini
MCP_SERVER_URL="https://mcp-https.DASHED_EXTERNAL_IP.sslip.io/mcp/"
MCP_SERVER_LABEL="wiki"

Launch the agent in Azure AI Agent Service:

```bash
cd mcp-wiki/agent-service
uv run agent_mcp_wiki.py
```

The agent code loads its required configuration values from the .env file (see .env_template for variable names).

    - Project endpoint + model
    - MCP server URL (must be HTTPS)

and attaches the MCP tool
  (See: [mcp-wiki/agent-service/agent_mcp_wiki.py](mcp-wiki/agent-service/agent_mcp_wiki.py))

## 11. Health & Debug

```bash
# Pod logs
kubectl -n mcp-wiki-https logs deploy/mcp-wiki-server-https

# Port-forward for local curl
kubectl -n mcp-wiki-https port-forward svc/mcp-wiki-service-https 8080:80
curl -sS http://127.0.0.1:8080/healthz
```

## 12. Troubleshooting

| Issue         | Check                                                                          |
| ------------- | ------------------------------------------------------------------------------ |
| 404 /mcp      | Missing trailing slash in client; ensure Ingress has both `/mcp` & `/mcp/` |
| 502/timeout   | Increase proxy timeout annotations                                             |
| No cert       | `kubectl describe certificate` for ACME events                               |
| Pod CrashLoop | `kubectl logs` & image tag correctness                                       |
| Tool fails    | Wikipedia rate limit or network egress                                         |

## 13. Cleanup

```bash
az group delete -n rg-mcp-wiki-demo-ex --yes --no-wait
```

## 14. License

Licensed under the MIT License. See the [`LICENSE`](./LICENSE) file for the full text.

SPDX-License-Identifier: MIT
