# Brazilian Portuguese web interface

## Plan and session record

- Translate the station page, sign-in instructions, buttons and browser-facing
  error messages to Brazilian Portuguese; set the HTML language to pt-BR.
- Move all multiline docstring summaries in web/app.py to the second line.
- Keep internal status values, routes and authentication behavior unchanged.
- Ruff D213 passed. Temporary rendering checks passed for sign-in states,
  station results and validation messages. No formal test suite was added.
- Automatic reload through the user's development Gunicorn remains for the user
  to verify by refreshing the browser.

## Method-call examples

```text
GET /cn3s-test
GET /cn3s-test/station?station=14558000
```
