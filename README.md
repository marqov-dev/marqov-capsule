# marqov-capsule

Standalone capsule format for reproducible quantum-classical workflows.

## Install

```bash
pip install marqov-capsule                # core: build, seal, verify
pip install marqov-capsule[verify]        # + statistical verification
pip install marqov-capsule[validate]      # + schema validation
```

## Quick Start

```python
from marqov_capsule import CapsuleBuilder, CapsuleVerifier

# Build
builder = CapsuleBuilder("my-analysis", description="Example capsule")
builder.start_capsule(parameters={"distance": 3})
builder.add_task_execution(task_id="main", backend="local", outputs={"result": 42})
builder.seal_capsule(exit_code=0)
builder.save_capsule("my-analysis.capsule/capsule.yaml")

# Verify
verifier = CapsuleVerifier()
capsule = verifier.load_capsule("my-analysis.capsule/capsule.yaml")
result = verifier.verify_capsule(capsule)
print(result["verification_passed"])  # True
```
