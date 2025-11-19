#!/usr/bin/env python3
"""
Wrapper script to run the kaspr-operator with Kopf.

This script applies the kubernetes_asyncio patch BEFORE Kopf is loaded,
then launches Kopf's CLI with all standard arguments.

Usage:
    python run_operator.py [any kopf run arguments]
    
Examples:
    python run_operator.py --verbose --all-namespaces
    python run_operator.py -n my-namespace --log-format=json
"""

# CRITICAL: Apply patch BEFORE any kopf imports
from kaspr.utils.override import patch_kopf_thirdparty
patch_kopf_thirdparty()

# Now safe to import and run kopf  # noqa: E402
import sys  # noqa: E402

if __name__ == '__main__':
    # Import kopf after patch is applied
    import kopf.cli  # noqa: E402
    
    # Import the operator module (which registers handlers via decorators)
    import kaspr.app  # noqa: E402, F401
    
    # Inject 'run' as the command since we're calling the CLI directly
    # This makes it behave as if user called: kopf run <args>
    
    sys.argv.insert(1, 'run')
    
    # Call Kopf's CLI main entry point - it handles all argument parsing
    sys.exit(kopf.cli.main(prog_name="kopf"))
