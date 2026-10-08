"""Collect emails (and names) from a zip of messy files into one subscriber CSV."""

NEWSLETTER_PREF = "The IDR Weekly||Off The Record"
OUT_COLUMNS = ["email", "First Name", "Last Name", "Newsletter Preference"]

# Newsletter Preference value per audience. Hindi subscribers have no preference (blank).
AUDIENCES = {"english": NEWSLETTER_PREF, "hindi": ""}
