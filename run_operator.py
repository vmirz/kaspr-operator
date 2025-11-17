#!/usr/bin/env python3
"""
Wrapper script to run the kaspr-operator with Kopf.

This script applies the kubernetes_asyncio patch BEFORE Kopf is loaded,
then launches Kopf programmatically.

Usage:
    python run_operator.py [--verbose] [--all-namespaces] [other kopf args]
"""

# CRITICAL: Apply patch BEFORE any kopf imports
from kaspr.utils.override import patch_kopf_thirdparty
patch_kopf_thirdparty()

# Now safe to import and run kopf  # noqa: E402
import sys  # noqa: E402
import logging  # noqa: E402

if __name__ == '__main__':
    # Import kopf after patch is applied
    import kopf  # noqa: E402
    
    # Import the operator module (which registers handlers via decorators)
    import kaspr.app  # noqa: E402, F401
    
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description='Run the Kaspr Operator')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--all-namespaces', '-A', action='store_true', help='Watch all namespaces')
    parser.add_argument('--namespace', '-n', type=str, help='Watch specific namespace')
    parser.add_argument('--dev', action='store_true', help='Run in development mode')
    parser.add_argument('--standalone', action='store_true', default=True, help='Run in standalone mode (default)')
    
    args, unknown = parser.parse_known_args()
    
    # Set up logging based on verbosity
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='[%(asctime)s] %(name)-20s [%(levelname)-8s] %(message)s',
    )
    
    # Prepare kopf.run arguments
    run_kwargs = {
        'standalone': args.standalone,
    }
    
    # Handle namespace watching
    if args.all_namespaces:
        run_kwargs['clusterwide'] = True
    elif args.namespace:
        run_kwargs['namespaces'] = [args.namespace]
    else:
        # Default to clusterwide if neither is specified
        run_kwargs['clusterwide'] = True
    
    # Run the operator using kopf.run (CLI-compatible interface)
    # This handles signal handlers, logging setup, and other CLI features
    sys.exit(kopf.run(
        **run_kwargs
    ))
