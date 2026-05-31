# Current AI Model Fallback Debt

The current codebase contains multiple Gemini model fallback lists, including legacy 2.0 and 1.5 models in some tools. For this audit, that behavior is documented as compatibility debt rather than silently changed; a focused follow-up should align code and docs to the supported model policy after verifying PyLOAD, PyLOG, PyLIVE, and PyCUT behavior.
