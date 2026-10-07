Subject: SEC connector v9 + OCR - three-document setup and import

Hi,

The v9 + OCR setup package is ready for a fresh installation alongside your
existing connector. It covers the complete PNC 2025 proxy and both the FY2023
and FY2024 annual reports, with no exhibits or sampled pages.

Please use the reviewed commit supplied with this delivery and follow
[the setup and import runbook](customer-v9-setup.md), using the included
[configuration](../config/customer-v9/config.yaml) and
[exact-document manifest](../config/customer-v9/documents.yaml).
The first phase downloads the three selected SEC documents, stages their required
rotated-name images, and builds the upload payloads locally. It does not need
Microsoft 365 credentials or contact Microsoft Graph.

Local validation produced 2,198 payloads and recognized all 13 distinct
director-name images in the proxy. This confirms local preparation for the
specified source documents, not Microsoft 365 indexing or answer accuracy.
No new Microsoft 365 upload was performed during this validation.

After reviewing the local results, your administrator can authorize the separate
live steps: create a new app and unused connection, grant the two documented
Graph application permissions with admin consent, and import the reviewed bundle.
All three documents use the same new connection and database. The procedure
leaves your existing connector, app, data and agent unchanged.

Please obtain Python dependencies and the complete native Tesseract/English-model
bundle through your organization's approved software sources. The runbook includes
secure credential entry and exact retry commands.

Thank you.
