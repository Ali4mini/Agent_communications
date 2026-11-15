#!/usr/bin/env bash
# Self-signed cert for the porch (pin the fingerprint in guides).
# Replace with ACME once the porch gets a domain.
set -e
cd "$(dirname "$0")"
if [ -f porch.crt ] && [ -f porch.key ]; then echo "cert exists, skip"; exit 0; fi
openssl req -x509 -newkey rsa:2048 -days 825 -nodes \
  -keyout porch.key -out porch.crt \
  -subj "/CN=porch" -addext "subjectAltName=IP:65.109.210.175,DNS:porch" 2>&1 | tail -1
chmod 600 porch.key; chmod 644 porch.crt
FP=$(python3 -c "import ssl,hashlib; d=ssl.PEM_cert_to_DER_cert(open('porch.crt').read()); h=hashlib.sha256(d).hexdigest().upper(); print(':'.join(h[i:i+2] for i in range(0,len(h),2)))")
echo "FINGERPRINT: $FP"
