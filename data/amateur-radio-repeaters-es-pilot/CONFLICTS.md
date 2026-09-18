# Conflicts

Policy: `prefer_ure` for URE-published callsign, site coordinates, frequency and operating parameters; `prefer_radioid` for DMR color code/network; otherwise `manual_review`.

| callsign | field | source A/value | source B/value | recommended_resolution | rationale | confidence |
| --- | --- | --- | --- | --- | --- | --- |
| ED4ZAG | offset_mhz | URE repeater and beacon listings / -0.0076 | RadioID.net DMR repeater API / -7.6 | manual_review | URE publishes a kHz unit while RadioID publishes an MHz offset; retain the literal normalized URE value until the site operator confirms the unit. | high |
| ED7ZAM | modes | URE repeater and beacon listings / C4FM | RadioID.net DMR repeater API / DMR | manual_review | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. | medium |
