# License & Sustainability

## The short version

covtest is **free forever** for:

- Individual developers (including at commercial companies) running it locally
- Open source projects
- NGOs and non-profit organizations
- Educational institutions at all levels
- Public research institutions

**Commercial CI/CD use** by for-profit companies requires a monthly sponsorship.

[Sponsor on GitHub :octicons-heart-fill-24:{ .heart }](https://github.com/sponsors/memsharded){ .md-button .md-button--primary }

---

## Why this license exists

Open source has a sustainability problem.

Tools like covtest take significant time to build, maintain, and improve: adding support for new Python versions, keeping up with pytest and coverage changes, fixing bugs, writing documentation, answering questions. That work is real, and it needs to be funded somehow.

The traditional options are not great:

- **Pure open source (MIT/Apache):** Anyone can use it, including large companies that benefit enormously from it, without any obligation to contribute back. Maintainers burn out.
- **Fully proprietary:** Excludes the developer community that gives feedback, finds bugs, and spreads the word. The tool stagnates.
- **VC-backed open core:** Introduces investor pressure to extract value from users rather than serve them.

The model here is different: **the community gets it free, commercial beneficiaries pay a small amount to keep it alive.**

---

## The logic of the boundary

The free/paid line is drawn at **server-side CI use by for-profit organizations**, not at "developer has a job."

Here is why:

- An individual developer running covtest locally gets faster feedback loops. That's a personal productivity gain. It costs nothing.
- A company running covtest in CI pipelines gets reduced infrastructure costs and faster build times at scale — potentially saving thousands of dollars per month. That's organizational value derived directly from the tool.

The ask is proportional: a small monthly sponsorship from the organizations that extract the most value, so the tool can remain healthy for everyone.

---

## What this license does NOT restrict

This is a **tool**, not a library. It does not link into your code, it does not become part of your product, and it does not impose any conditions on what you build.

Specifically:

- Your source code is yours, under whatever license you choose.
- Your test files are yours.
- Projects that *use* covtest are not subject to this license.
- The coverage snapshots covtest produces are yours.

Using covtest in a commercial project does not make your project "open source" or subject it to any copyleft requirement.

---

## Comparison to similar licenses

Several projects have faced this same sustainability challenge and adopted "source-available" licenses:

| License | Used by | Main restriction |
|---------|---------|-----------------|
| Business Source License (BSL 1.1) | HashiCorp/Terraform, MariaDB | Restricts competitive/production use; auto-converts to GPL after 4 years |
| Functional Source License (FSL) | Sentry, Liquibase | Same idea as BSL; converts to Apache 2.0 after 2 years |
| Commons Clause | Redis, Confluent | Forbids selling the software as a managed service |

covtest's license is narrower than all of these. It does not restrict:

- Internal production use (deploying your app built with covtest-accelerated CI is fine)
- Building a product that was tested with covtest
- Self-hosting or running covtest as a service internally

The only thing it restricts is **running covtest itself in commercial CI pipelines without a sponsorship**. That is the most targeted ask possible.

None of these licenses (including covtest's) are OSI-approved "open source." covtest is **source-available**: the code is public, contributions are welcome, but commercial CI use requires a sponsorship.

---

## How to get a commercial license

Sponsoring the project on GitHub Sponsors constitutes your commercial license. Pick any tier that fits your organization's size and usage.

[View sponsorship tiers](https://github.com/sponsors/memsharded){ .md-button }

If your organization needs a formal license agreement or invoice, [open an issue](https://github.com/memsharded/covtest/issues) or contact the maintainer directly.

---

## Full license text

See the [LICENSE](https://github.com/memsharded/covtest/blob/main/LICENSE) file in the repository root.
