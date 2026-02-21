# Kubernetes ile Dağıtım

Elyan'ı Kubernetes'e dağıtmak için resmi Helm chart'ı kullanın.

## Gereksinimler

- Kubernetes 1.24+
- Helm 3.10+
- Persistent Volume provisioner (disk kalıcılığı için)

## Hızlı Kurulum

```bash
# Repo clone
git clone https://github.com/your-org/elyan.git
cd elyan

# Minimum kurulum
helm install elyan ./helm/elyan \
  --set secrets.data.TELEGRAM_BOT_TOKEN=<token> \
  --set secrets.data.GROQ_API_KEY=<key> \
  --namespace elyan --create-namespace
```

## Üretim Yapılandırması

`values-prod.yaml` örneği:

```yaml
replicaCount: 2

image:
  tag: "18.0.0"

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: elyan.mycompany.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: elyan-tls
      hosts:
        - elyan.mycompany.com

resources:
  requests:
    cpu: 500m
    memory: 1Gi
  limits:
    cpu: "2"
    memory: 4Gi

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 5
  targetCPUUtilizationPercentage: 65

persistence:
  size: 10Gi
  storageClass: fast-ssd

secrets:
  create: false
  existingSecret: elyan-prod-secrets  # External Secrets Operator ile yönetilir
```

Uygula:

```bash
helm upgrade --install elyan ./helm/elyan \
  -f values-prod.yaml \
  --namespace elyan
```

## Sırların Yönetimi

Üretimde API anahtarlarını **External Secrets Operator** veya **Vault** ile yönetin:

```bash
# AWS Secrets Manager örneği
kubectl create secret generic elyan-prod-secrets \
  --from-literal=TELEGRAM_BOT_TOKEN="..." \
  --from-literal=GROQ_API_KEY="..." \
  --namespace elyan
```

## Durum Kontrolü

```bash
helm status elyan -n elyan
kubectl get pods -n elyan
kubectl logs -f deployment/elyan -n elyan
```

## Güncelleme

```bash
helm upgrade elyan ./helm/elyan -n elyan \
  --set image.tag=18.1.0
```

## Kaldırma

```bash
helm uninstall elyan -n elyan
kubectl delete namespace elyan
```
