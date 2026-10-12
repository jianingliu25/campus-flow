# Original workspace audit — 2026-10-12

The parent workspace contains course reports, presentation/PDF materials, images,
an archived ZIP, explanatory documents, and a nested React project.
The workspace root is not a Git repository. This reconstruction has its own `.git`.

The existing `campus_flow/campus_flow/src/App.tsx` is the Vite/React counter template.
Its package.json declares React/TypeScript/Vite/Tailwind. The checked source files
do not contain campus business functions, a backend, ingestion, or SMOA code.
The UI reference is therefore a product reference, not proof of existing implementation.

No course source, old dependency folder, archive, real-mail export, private agent
session, report, or UI image was copied into the new repository. New sample emails,
preview code and documentation were authored from scratch.

The previous agent-session text and `.claude` directory are excluded from reuse
because they may contain private context. They were not needed for reconstruction.

`legacy-inventory.json` records relative paths, byte counts and SHA-256 hashes of
nine selected reference/old-code files for preservation checks. It contains no file
contents or absolute user paths. The new repository is `campus-flow-open/` only.

This audit does not establish copyright ownership of the course team's artifacts.
They remain outside this repository. The MIT license covers the newly authored
reconstruction and fictional fixtures, not excluded original artifacts or models.
