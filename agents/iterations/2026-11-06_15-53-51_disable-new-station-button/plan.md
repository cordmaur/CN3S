# Disable new station button

## Plan and session record

- Add the native disabled attribute to the + Inserir nova estação button.
- Remove new-station from setBusy's toggle list so completing an operation cannot re-enable it.
- Existing disabled-button CSS supplies the visual state. Insertion backend and station editing remain unchanged.
- Static assertions confirmed the disabled attribute and updated control list; affected-file whitespace checks passed. JavaScript syntax checking was unavailable because Node is not installed.

## Method-call example

`setBusy(false)` restores operation controls while the new-station button remains disabled.
