#!/usr/bin/env sh
# Metheon on a local Kind cluster.
#
#   k8s/dev.sh up       create the cluster, build and load the image, deploy
#   k8s/dev.sh deploy   rebuild, reload and roll out after a code change
#   k8s/dev.sh status   what is running
#   k8s/dev.sh down     delete the cluster
#
# Everything here is local: Kind runs the cluster in Docker on this machine.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
cluster=metheon
image=metheon-backend

cluster_exists() {
  kind get clusters 2>/dev/null | grep -qx "$cluster"
}

build_and_load() {
  echo "-> building $image"
  docker build -q -t "$image" "$root/backend" >/dev/null
  echo "-> loading $image into the cluster"
  kind load docker-image "$image" --name "$cluster"
}

apply() {
  echo "-> applying manifests"
  kubectl apply -k "$here"
  # init.sql lives with the backend; see kustomization.yaml for why it is
  # not generated there. Idempotent: the same content is applied each time.
  kubectl create configmap postgres-init \
    --namespace metheon \
    --from-file=init.sql="$root/backend/app/db/init.sql" \
    --dry-run=client -o yaml | kubectl apply -f -
}

wait_ready() {
  echo "-> waiting for postgres, redis, api and worker"
  kubectl rollout status statefulset/postgres -n metheon --timeout=180s
  kubectl rollout status deployment/redis -n metheon --timeout=120s
  kubectl rollout status deployment/api -n metheon --timeout=180s
  kubectl rollout status deployment/worker -n metheon --timeout=180s
  echo "-> API at http://localhost:8080/api/health"
}

case "${1:-}" in
  up)
    if cluster_exists; then
      echo "cluster '$cluster' already exists; use 'deploy' or 'down' first"
      exit 1
    fi
    kind create cluster --config "$here/kind-config.yaml"
    build_and_load
    apply
    wait_ready
    ;;
  deploy)
    cluster_exists || { echo "no cluster; run 'up' first"; exit 1; }
    build_and_load
    apply
    # Same image tag, so a plain apply changes nothing: force new pods.
    kubectl rollout restart deployment/api deployment/worker -n metheon
    wait_ready
    ;;
  status)
    kubectl get pods,svc,pvc -n metheon
    ;;
  down)
    kind delete cluster --name "$cluster"
    ;;
  *)
    sed -n '2,9p' "$0"
    exit 1
    ;;
esac
