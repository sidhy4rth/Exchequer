# Archived launch-film composition

This folder is the source of a launch film that has already been rendered and
delivered (the `.mp4` one folder up). It is kept for the record, not as a
working project, so a coding agent opened here should change nothing.

- Do not install, update or download anything: no `npx` tool other than the
  pinned one below, no skills, no `@latest` upgrades, no `npm install`.
- Do not publish. `npm run publish` uploads the film to a third-party host.
- To check or re-render the film exactly as it was made, use the CLI version
  `package.json` pins, and only by hand:

  ```bash
  npm run check    # npx --yes hyperframes@0.8.50 check
  npm run render   # npx --yes hyperframes@0.8.50 render
  ```

A new film starts in a new folder from a fresh `hyperframes init`, never by
editing this one.
