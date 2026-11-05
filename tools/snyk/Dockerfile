# Reviewed upstream Linux/amd64 image. Update the digest and expected CLI
# version together; CI checks the actual binary before AWS credentials exist.
FROM snyk/snyk:linux@sha256:cc5eaa3bde08920ce0e88329c0b65f3a7eeefcb43920f80471da2fa23de4efb3
LABEL org.devsecops.snyk-version="1.1308.4"
# Bypass the upstream entrypoint, which can download a different CLI at runtime.
ENTRYPOINT ["/usr/local/bin/snyk"]
