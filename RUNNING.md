# Kopf Override - How to Run the Operator

## The Problem with `kopf run`

When you run `kopf run kaspr/app.py`, here's the sequence:

1. The `kopf` CLI module is loaded
2. All of Kopf's internal modules are imported, including `kopf._cogs.helpers.thirdparty`
3. **Then** it loads `kaspr/app.py`
4. By this time, it's **too late** - the patch in `kaspr/app.py` cannot replace a module that's already loaded

## The Solution: Wrapper Script

We use `run_operator.py` which:
1. Applies the patch FIRST
2. Then imports and runs Kopf

### Development

Use the VS Code launch configuration "Python Debugger: Kopf Operator (with patch)" which runs:
```bash
python run_operator.py
```

Or run manually:
```bash
python run_operator.py
# Or with custom args:
python run_operator.py run kaspr/app.py --all-namespaces --verbose
```

### Production (Docker)

The Dockerfile is configured to use the wrapper:
```dockerfile
CMD ["python3", "/usr/src/app/run_operator.py"]
```

## Why the Patch is Needed

The operator uses `kubernetes_asyncio` for better async/await support, but Kopf only recognizes models from the standard `kubernetes` client. The patch in `kaspr/utils/override.py` extends Kopf's model detection to also recognize `kubernetes_asyncio` models.

**Note:** There is an open PR ([#809](https://github.com/nolar/kopf/pull/809)) to add this support directly to Kopf. Once that PR is merged and released, we can remove this patch and return to using `kopf run kaspr/app.py` directly.

## Verification

The wrapper script will print:
```
[kaspr] Applied Kopf thirdparty patch for kubernetes_asyncio support
```

If you don't see this message, the patch wasn't applied correctly.
