# MCP Wiki Server on AKS

Minimal Model Context Protocol (MCP) server exposing a single `answerQ` tool that returns Wikipedia summaries. Runs locally, in Docker, and on Azure Kubernetes Service (AKS) with HTTPS + cert-manager. Integrates with VS Code MCP clients and Azure AI Agent Service.

## 1. Features

- Single MCP tool: `answerQ`
- Streamable HTTP endpoint (`/mcp/`) with JSON/SSE
- Health endpoint: `/healthz`
- Docker image
- Kubernetes Deployment + Service + Ingress (TLS via Let’s Encrypt)
- VS Code MCP client config
- Agent Service AI Agent Integration with MCP server

## 2. Key Files

- Server: [mcp-wiki/server/server.py](mcp-wiki/server/server.py)
- Dockerfile: [mcp-wiki/server/Dockerfile](mcp-wiki/server/Dockerfile)
- Agent script: [mcp-wiki/agent-service/agent_mcp_wiki.py](mcp-wiki/agent-service/agent_mcp_wiki.py)
- K8s manifests: [mcp-wiki/k8s/https](mcp-wiki/k8s/https)
- VS Code MCP config: [.vscode/mcp.json](.vscode/mcp.json)
- Env vars: [.env_template](.env_template)

## 3. Prerequisites

- Python 3.10+
- uv (https://docs.astral.sh/uv)
- Docker
- Azure CLI (`az`)
- kubectl
- An Azure subscription + ACR + AKS
- (Optional) jq for JSON formatting

## 4. Local Setup

```bash
git clone https://github.com/vladfeigin/foundry-agent-service-mcp-demo.git
cd foundry-agent-service-mcp-demo/mcp-wiki
uv sync
uv run uvicorn server.server:starlette_app --host 0.0.0.0 --port 4200
```

Health:

```bash
curl -s http://localhost:4200/healthz
```

List tools (NOTE trailing slash /mcp/):

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

Build & run:

```bash
Run locally docker with MCP server
docker build -f server/Dockerfile -t mcp-wiki-server .
docker run -p 4200:4200 mcp-wiki-server
```

Now you have a MCP sever running locally in a Docker container.

### Connecting to local MCP Server

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

Great! Now we have a working local MCP server.

## 6. Creating Azure Resources

Change the names, location and other parameters as needed. Here is just an example:

```bash
crate Resource Group
az group create -n rg-mcp-wiki-demo-ex -l swedencentral
create Container Registry
az acr create -g rg-mcp-wiki-demo-ex -n mcpwikidemoex --sku Basic --admin-enabled true
create AKS cluster
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

```bash
Login to ACR:
az acr login -n mcpwikidemoex
Build Multi-arch container for Linux push to ACR:
docker buildx build \
  --platform linux/amd64 \
  -f server/Dockerfile \
  -t mcpwikidemoex.azurecr.io/mcp-wiki-server:v1.0.1 \
  --push .
```

Now we have a MCP server container for Linux pushed to ACR.

## 7. Deploy to AKS

Azure Foundry expects your MCP server to be reachable over HTTPS only. So we need to install cert-manager CRDs for clusterissuer.cert-manager.io.

```bash
helm install cert-manager oci://quay.io/jetstack/charts/cert-manager \
  --version v1.18.2 \
  --namespace cert-manager \
  --create-namespace \
  --set crds.enabled=true
```

Check it was installed  properly

```bash
kubectl get pods -n cert-manager
kubectl get crd | grep cert-manager.io
```

To receive HTTPS traffic, we need to install Ingress Controller. In this project we use Managed NGINX Ingress
[Nginx Ingress Controller](https://learn.microsoft.com/en-us/azure/aks/app-routing?utm_source=chatgpt.com#enable-application-routing-using-azure-cli "Nginx Ingress")

Enable it on the existing cluster, run:

```bash
az aks approuting enable --resource-group rg-mcp-wiki-demo-ex --name aks-mcp-wiki-ex
```

Before you running `kubectl apply` for the manifests make sure you've following changes:

1. Update image name to the corect ACR image path.
   In [mcp-wiki/k8s/deployment.yaml](mcp-wiki/k8s/deployment.yaml):

   ```yaml
   spec:
     containers:
     - name: mcp-wiki-server
       image: mcpwikidemoex.azurecr.io/mcp-wiki-server:v1.0.1   # <— your image
   ```
2. Find the external IP of the Ingress Controller (the managed NGINX ingress controller runs in the `app-routing-system` namespace):

   ```bash
   kubectl get svc -n app-routing-system
   ```
3. Update host name in [mcp-wiki/k8s/ingress.yaml](mcp-wiki/k8s/ingress.yaml):
   Note: This example uses the wildcard DNS service sslip.io (https://sslip.io/), which maps <IP_ADDRESS>.sslip.io (and hostnames containing it) to the given IP. This is fine for demos; for production use a real domain and managed DNS.

   Convert the external IP to dash notation (replace dots with dashes):
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

    Replace <DASHED_EXTERNAL_IP> with the dash-formatted external IP (e.g., 1-234-56-78).

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

Now, we'll create an AI Agent in Foundry Agent Service and configure its tools as a MCP server, which we just built before.

Populate [.env](.env).

PROJECT_ENDPOINT="your AI Foundry project endpoint"

MODEL_DEPLOYMENT_NAME="your LLM deployment name in AI Foundry project "

MCP_SERVER_URL="https://mcp-https.DASHED_EXTERNAL_IP.sslip.io/mcp/"

MCP_SERVER_LABEL="wiki"

Run:

```bash
cd mcp-wiki/agent-service
uv run agent_mcp_wiki.py
```

Script uses:

- Project endpoint + model
- MCP server URL (must be HTTPS)
- Attaches MCP tool and runs `answerQ`
  (See: [mcp-wiki/agent-service/agent_mcp_wiki.py](mcp-wiki/agent-service/agent_mcp_wiki.py))

## 11. Health & Debug

```bash
# Pod logs
kubectl -n mcp-wiki-https logs deploy/mcp-wiki-server-https

# Port-forward for local curl
kubectl -n mcp-wiki-https port-forward svc/mcp-wiki-service-https 8080:80
curl -sS http://127.0.0.1:8080/healthz
```

## 13. Troubleshooting

| Issue         | Check                                                                          |
| ------------- | ------------------------------------------------------------------------------ |
| 404 /mcp      | Missing trailing slash in client; ensure Ingress has both `/mcp` & `/mcp/` |
| 502/timeout   | Increase proxy timeout annotations                                             |
| No cert       | `kubectl describe certificate` for ACME events                               |
| Pod CrashLoop | `kubectl logs` & image tag correctness                                       |
| Tool fails    | Wikipedia rate limit or network egress                                         |

## 14. Cleanup

```bash
az group delete -n rg-mcp-wiki-demo --yes --no-wait
```

## 15. License
Licensed under the MIT License. See the [`LICENSE`](./LICENSE) file for the full text.
