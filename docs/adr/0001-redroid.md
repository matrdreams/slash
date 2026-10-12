# ADR 0001: Redroid

Android runs in a privileged container that shares the host kernel. The preferred host is arm64 with a 4K page size so app libraries do not need translation. amd64 images are supported for development and use the translation library shipped in the official image.

ADB is bound to 127.0.0.1. A container cannot load `binder_linux`; `check.sh` rejects that environment.
