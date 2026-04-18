# Kubernetes deployment

This folder provides production-style Kubernetes manifests for the Nava AI project.

## Included resources

- namespace.yaml: dedicated namespace
- configmap.yaml: runtime configuration values
- secret.example.yaml: template for API secrets
- redis-deployment.yaml: Redis deployment
- api-deployment.yaml: FastAPI deployment
- worker-deployment.yaml: RQ worker deployment with GPU node scheduling hints
- services.yaml: API and Redis services
- ingress.yaml: external routing for API
- worker-hpa.yaml: queue-depth autoscaling via KEDA plus CPU fallback HPA
- servicemonitor.yaml: Prometheus Operator scrape config

## Prerequisites

- A container registry image for this app (replace `nava-ai:latest` if needed).
- KEDA installed in the cluster for queue-depth autoscaling.
- Optional: Prometheus Operator for ServiceMonitor support.

## Apply order

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.example.yaml
kubectl apply -f k8s/redis-deployment.yaml
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/worker-deployment.yaml
kubectl apply -f k8s/services.yaml
kubectl apply -f k8s/ingress.yaml
kubectl apply -f k8s/worker-hpa.yaml
kubectl apply -f k8s/servicemonitor.yaml
```

## Notes

- Worker autoscaling trigger uses Redis queue key `rq:queue:eonet-inference`.
- KEDA ScaledObject creates and manages an HPA resource automatically.
- Worker deployment includes:
  - nodeSelector `accelerator: nvidia`
  - GPU toleration key `nvidia.com/gpu`
  - GPU limit `nvidia.com/gpu: 1`
- If your cluster uses different GPU labels, update nodeSelector and tolerations.
