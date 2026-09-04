"""
Azure integrations, all optional.

Every module here imports its Azure SDK lazily, inside the function that needs
it. That is deliberate: local development installs only requirements.txt, never
touches these code paths, and must not fail on a missing azure-* package.

Install the Azure extras with:
    pip install -r requirements-azure.txt
"""
