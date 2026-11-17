# Playbook: Summit Federal Benefits (federal portal)

1. Log in with the leased credential, then complete two-step verification with `enter_totp`.
   - "Invalid credentials" means the credential is bad. Do not retry it more than once; finish as needs_human.
   - "Account locked" means stop immediately and finish as needs_human.
   - "Your session ended because you signed in elsewhere" means log in again.
2. Start a new request. Step 1: member number and member last name.
3. Step 2: tick each CPT code checkbox. Dates must be typed MM/DD/YYYY.
   Answer "continuation of an existing authorization?" (normally No) and "admitted inpatient?" (normally No)
   from the case documents.
4. Step 3: upload the treatment plan as Document 1 and choose type "Treatment plan". PDF only.
5. Step 4: tick the attestation and submit. A 503 error is temporary: wait and resubmit once or twice.
6. Read the confirmation. Tracking IDs start with SFB-T-.
