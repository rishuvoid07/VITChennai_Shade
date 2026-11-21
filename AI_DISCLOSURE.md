# AI Disclosure
Team Shade (Rishabh Jain, VIT Chennai), XR Hackathon 2026, Track 3.
- Design and review: Claude (Anthropic) was used as a design and review assistant: discussing algorithm options, planning experiments, reviewing measured results, and drafting the README, presentation and this disclosure.
- Implementation: coding agents in the Antigravity IDE (models selected in the tool: Gemini and Claude) wrote and ran the code, tests and measurement scripts under the author's direction.
- Human role: the author set the goals and constraints, ran and reviewed every measurement, decided which results to accept, and made the submission.
- Algorithms and data: the tilt filter follows the published Mahony complementary filter. All reported numbers were measured on EuRoC MAV sequences (MH_01, V1_01), degraded with the organizers' degrade_imu.py. No dataset files are included in this repository.
