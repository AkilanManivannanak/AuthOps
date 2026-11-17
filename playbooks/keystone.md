# Playbook: Keystone Community Medicaid (MCO portal)

1. Log in with the leased credential.
2. A maintenance notice pops up about a second after the page loads. Wait, then press "Acknowledge".
3. The request form is inside a frame on the page. Fields are reachable normally.
4. Medicaid ID must be typed as XXX-XXXXXXXX (three letters, dash, eight digits). The field adds the dash.
5. Dates use a calendar widget, not typing. Use `pick_date` with the ISO date.
6. If Service Category is ABA, two more questions appear:
   - "Is a school schedule attached?" answer from the case documents (`query_document`).
   - "Requested hours on school days" answer from the treatment plan frequency.
7. Attach the treatment plan and submit. Reference numbers start with KC-.
