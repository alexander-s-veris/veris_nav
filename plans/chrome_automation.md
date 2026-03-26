# Chrome Integration — Automated Document Collection

## Status: Setup pending (extension installed, connection not yet working)

## Goal

Use Claude Code's Chrome integration to automatically fetch authenticated documents from external sources, eliminating manual downloads.

## Use Cases

- **DocSend loan notices**: FalconX/Pareto monthly interest rate notices at `https://docsend.com/view/s/ue5jyarwup3fy9v6/f/fwzeuemsghdteyxb` (credentials: alexander.s@veris-digital.com)
- **Issuer NAV reports**: Any password-protected or email-gated NAV reports from fund issuers
- **DeBank verification**: Cross-check portfolio values from authenticated DeBank profiles
- **Any other authenticated web source** that currently requires manual copy-paste

## Setup

1. Chrome extension "Claude in Chrome" is installed
2. Need to establish connection — may require fresh Claude Code session
3. Run `/chrome` to enable, then reconnect extension
4. Once working, can navigate authenticated pages and extract data directly

## How to Apply

Once Chrome integration works, the monthly NAV workflow becomes:
1. Open Chrome, log into DocSend / issuer portals
2. Start Claude Code with `/chrome` enabled
3. Ask Claude to fetch the latest loan notices, extract rates, and update configs
4. No manual downloads needed — Claude reads authenticated pages directly
