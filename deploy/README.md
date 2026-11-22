# Uruchomienie w bezpiecznym środowisku / Running in an isolated environment

Two options, both offline at run time (models and reference sets are baked into the image during the build; only the build needs network).

## 1. Docker Compose (hardened)

```bash
mkdir -p runs
docker compose build                                    # once, needs network (~20 min, CPU only)
docker compose run --rm app fakecollector run data/<known> --out runs/base --profile full
docker compose -f docker-compose.yml -f docker-compose.secure.yml up
# UI: http://127.0.0.1:3000
```

`docker-compose.secure.yml` puts the API on an internal network with no route to the internet, drops all Linux capabilities, forbids privilege escalation, runs the UI with a read-only root filesystem, sets CPU/memory limits and publishes ports on localhost only. Both images run as non-root users (uid 1000).

## 2. Kubernetes (`deploy/k8s/`)

Manifests: namespace with Pod Security `restricted`, two PVCs (`kf-data` with your material, `kf-runs` with results), ConfigMap, API Deployment + Service `app`, web Deployment + Service `kf-web`, NetworkPolicies (default deny, no egress outside the namespace, web → API only), and a one-off Job that builds the base. All pods: non-root, no capabilities, no privilege escalation, `RuntimeDefault` seccomp, no service-account token, resource limits.

```bash
# 1. Build the images and make them available to the cluster
docker compose build                       # images: fakecollector, fakecollector-web
kind load docker-image fakecollector:latest fakecollector-web:latest      # kind
# minikube image load fakecollector:latest && minikube image load fakecollector-web:latest
# (or push both to your registry and change `image:` in api.yaml, web.yaml, job-build-base.yaml)

# 2. Namespace, storage, API and UI
kubectl apply -k deploy/k8s

# 3. Copy your material into the data volume (e.g. through a helper pod)
kubectl -n kolekcjoner run kf-copy --image=fakecollector:latest --restart=Never \
  --overrides='{"spec":{"securityContext":{"runAsNonRoot":true,"runAsUser":1000,"fsGroup":1000,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"kf-copy","image":"fakecollector:latest","command":["sleep","3600"],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}},"volumeMounts":[{"name":"d","mountPath":"/app/data"}]}],"volumes":[{"name":"d","persistentVolumeClaim":{"claimName":"kf-data"}}]}}'
kubectl -n kolekcjoner cp ./data/known kf-copy:/app/data/known
kubectl -n kolekcjoner delete pod kf-copy

# 4. Build the base (edit the input folders in job-build-base.yaml if needed), then restart the API
kubectl apply -f deploy/k8s/job-build-base.yaml
kubectl -n kolekcjoner wait --for=condition=complete job/kf-build-base --timeout=30m
kubectl -n kolekcjoner rollout restart deployment/kf-api

# 5. Open the UI
kubectl -n kolekcjoner port-forward svc/kf-web 3000:3000   # http://localhost:3000
```

New material can then be analysed on the UI page **Analizuj reklamę** (upload a screenshot, HAR, MHTML, PDF, video, a URL or a product name), or with a Job running `fakecollector assign data/<new> --against runs/base`.

Optional login for the UI: `kubectl -n kolekcjoner create secret generic kf-web-auth --from-literal=user=jury --from-literal=password=<password>` and restart `kf-web`.

Notes: `kf-runs` is ReadWriteOnce, so run the Job before (or while scaled down) the API on clusters that schedule them on different nodes. The NetworkPolicies need a CNI that enforces them (e.g. Calico or Cilium).
