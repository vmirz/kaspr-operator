"""HTTP server for exposing Prometheus metrics.

This module provides a simple HTTP server that exposes the /metrics endpoint
for Prometheus scraping. It uses the built-in prometheus_client HTTP server
in a background thread to avoid blocking the operator event loop.

The server starts automatically when imported and runs on port 8000 by default
(configurable via METRICS_PORT environment variable).
"""

import os
import logging
from threading import Thread
from prometheus_client import start_http_server

logger = logging.getLogger(__name__)


def start_metrics_server(port: int = 8000) -> None:
    """Start Prometheus metrics HTTP server in background thread.
    
    This starts a simple HTTP server that exposes metrics at http://0.0.0.0:port/metrics
    for Prometheus to scrape. The server runs in a daemon thread so it doesn't block
    operator shutdown.
    
    Args:
        port: Port to listen on (default: 8000)
    """
    try:
        start_http_server(port)
        logger.info(f"Prometheus metrics server started on port {port}")
        logger.info(f"Metrics available at http://0.0.0.0:{port}/metrics")
    except OSError as e:
        logger.error(f"Failed to start metrics server on port {port}: {e}")
        raise


def init_metrics_server() -> None:
    """Initialize metrics server with port from environment.
    
    Reads METRICS_PORT environment variable (default: 8000) and starts
    the server in a background thread.
    """
    port = int(os.environ.get('METRICS_PORT', '8000'))
    
    # Start server in daemon thread so it doesn't block shutdown
    thread = Thread(target=start_metrics_server, args=(port,), daemon=True)
    thread.start()
    
    logger.info(f"Metrics server initialization complete (port: {port})")
