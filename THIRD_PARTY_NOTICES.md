# Third-party Notices

Vybe-Check's authored code and examples use MIT. Dependencies installed independently by pip remain under their own licences. Declaring or importing a dependency doesn't mean its code or binaries are bundled in this project's wheel or source archive. Archive inspection is still required before any release claim.

## Observed Development Metadata

This preparatory inventory describes one development environment, not the final installed candidate or every supported host. Licence files were present in its installed distributions. Optional extras listed by those distributions aren't all runtime dependencies.

| Distribution | Observed version | Licence identifier | Role |
| --- | --- | --- | --- |
| Pillow | 12.3.0 | MIT-CMU | Core imaging dependency |
| portalocker | 4.4.0 | BSD-3-Clause | Core file-locking dependency |
| build | 1.6.1 | MIT | Development build tool |
| setuptools | 82.0.1 | MIT | Build backend |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | Development dependency |
| pyproject_hooks | 1.3.3 | MIT | Development dependency |
| pytest | 9.1.1 | MIT | Test runner |
| iniconfig | 2.3.0 | MIT | Test dependency |
| pluggy | 1.6.0 | MIT | Test dependency |
| Pygments | 2.21.0 | BSD-2-Clause | Test dependency |
| playwright | 1.63.0 | Apache-2.0 | Browser test tool |
| greenlet | 3.5.6 | MIT AND PSF-2.0 | Browser test dependency |
| pyee | 13.0.1 | MIT | Browser test dependency |
| typing_extensions | 4.16.0 | PSF-2.0 | Development transitive dependency |
| pip | 26.1.1 | MIT | Environment package manager |

Pillow's installed licence file contains notices for its own bundled components. Pip and setuptools also carry vendored notices. Those installed toolchain components don't become project redistribution merely because the tools run a build. Preserve their required notices if distributing those distributions or their binaries separately.

Optional native-store dependencies include keyring on non-Windows hosts and winrt-Windows.Security.Credentials on Windows. Their exact installed dependency graph and licence files have not been established by this development inventory. Treat missing or unknown licences as pending, inspect their actual metadata and texts on each verified host, and don't invent identifiers.

## Release Inspection Contract

Before distribution, inspect both the final wheel and sdist. Record every member, exact distribution versions, dependency graph with evaluated host/extra markers, licence identifiers, and licence-file hashes. Compare those members with the approved authored inventory. Inspect any bundled or redistributed third-party component and include its complete required licence text and attribution in both archives. Reject absent or unknown required notices. This source notice alone cannot close licence verification.

The package acceptance probes require explicit final wheel/sdist paths and run outside the source checkout. Final per-host installed metadata and redistribution inspections remain pending. Broad dependency ranges do not establish exact tested versions or support.
