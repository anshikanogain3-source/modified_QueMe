# QueMe — Project Implementation Report

This document describes the project as it is currently implemented, including local AI setup and runtime boundaries. Descriptions of optional services distinguish between code support and services that must be configured at runtime.

## 1. Project overview

QueMe is a campus placement interview practice application. Teachers prepare reusable interview questions, rubrics, and interview templates, then assign interviews to individual students or a class group. Students record answers in the browser. The backend stores the recordings, attempts transcription and analysis, generates feedback where configured, and makes a report available to the student and authorized staff.

The system has three roles:

| Role | Main responsibilities |
| --- | --- |
| Student | Register, see assigned interviews, give recording consent, answer questions, and review completed reports and recordings. |
| Teacher | Manage questions, rubrics, and templates; assign interviews; review reports and provide score overrides or remarks. |
| Admin | Approve accounts, configure class groups and score weights, view analytics/reports, and export report data. |

### Technology

- **Frontend:** React 18, React Router, Vite, and CSS in `frontend/src/styles.css`. Tailwind is configured in the frontend, although the current app's main visual system is implemented primarily with authored CSS classes.
- **Backend:** Flask REST API, SQLAlchemy, Flask-Migrate, and Flask-CORS.
- **Database:** Local SQLite file by default (`backend/queme.db` in the active local setup); PostgreSQL remains supported when explicitly configured. The interview flow tests use in-memory SQLite.
- **Authentication:** Bearer tokens, with password hashing and role checks in the backend.
- **Audio:** Browser `MediaRecorder` for capture and browser speech synthesis for spoken questions. Backend transcription uses `faster-whisper`; audio measurements are calculated by the audio-analysis service.
- **AI:** Local Ollama chat inference with Qwen 3 1.7B for question drafting, answer evaluation, and follow-up generation. Interview intelligence is not sent to a cloud LLM.
- **Audio storage:** The active local configuration targets AWS S3; local filesystem and Cloudflare R2 adapters remain available. Audio object keys are saved with interview answers in the configured database so reports can retrieve the recording through the authenticated backend.
- **Optional services:** SMTP password reset emails.

## 2. What is already implemented

### Public and account screens

- Marketing home page with product overview, feature cards, and links into account flows.
- Registration for students and teachers, with course/class-group fields.
- Login, pending-account information, forgot-password, and reset-password screens.
- Protected routes that redirect signed-out users to login and restrict role-specific pages.
- Shared app shell, navigation/branding, loading UI, and error/notice presentation.

New registrants are pending until an administrator activates them. The backend validates registration data and does not let a client self-assign the admin role.

### Student experience

- Student dashboard showing assigned interviews, interview statuses, progress, and completed-report links.
- Rapid-fire question practice using questions from the student's assigned interviews.
- Interview room with explicit recording consent, question text, optional speech playback, mute/replay controls, microphone recording, playback, re-record, submit, skip, and finish controls.
- Optional local camera preview. The preview is not uploaded as interview video; audio is the answer recording sent to the backend.
- Completed report page with per-question details, transcript/analysis where available, scoring and teacher feedback, and report export links.
- Student progress view with interview history and available score/audio comparisons.

### Teacher experience

- Teacher workspace and analytics for the teacher's assigned students/interviews.
- Question bank management and question drafting through the configured LLM provider when available.
- Draft review/commit flow that saves selected questions to the reusable question bank.
- Rubric management, including built-in seeded rubrics.
- Interview template creation and maintenance, with ordered question/rubric selections.
- Individual student and class-group interview assignments, scheduling, and cancellation of scheduled interviews.
- Report review with overall/per-question remarks and score overrides.

### Admin experience

- Approve/reject and filter user accounts.
- Create and manage course/class-group records used during registration and assignment.
- Configure content and delivery score weights.
- View campus analytics and recent reports, including reports requiring review.
- Download individual PDF/Excel reports and campus-wide Excel exports.

### Backend capabilities

- Application factory registers authentication, teacher-authoring, interview-session, report, and admin route groups.
- Database models cover users, courses/class groups (legacy internal department/batch names), questions, rubrics, templates, interview assignments, interview questions, audio-analysis results, reports, teacher question reviews, and system settings.
- Migrations maintain schema history; the initial admin, default rubrics, courses, and score weights are provisioned through the Flask `seed` command.
- Centralized API error responses, request validation, role/ownership authorization, health check, and database rollback/error handling.
- Audio upload validation, storage abstraction, transcription, recording-quality checks, communication metrics, rubric evaluation, follow-up generation, report analytics, PDF/Excel generation, and teacher review support.

## 3. Static and dynamic parts of the application

Here, **static** means content or behavior defined in the frontend source and shipped with the application. **Dynamic** means values or records loaded, created, or changed through application state, APIs, or the database.

| Area | Static (source-defined) | Dynamic (runtime/data-driven) |
| --- | --- | --- |
| Public site | Page layout, branding, explanatory copy, and feature descriptions. | Current year in the footer; navigation state such as the mobile menu. |
| Account screens | Form layout, field labels, validation presentation, and guidance text. | Registration options from API data; submitted credentials/profile; pending/active account state; login errors and authenticated user. |
| Dashboards | Card layouts, charts/sections, labels, and available actions. | Interview lists, counts, statuses, analytics, reports, class groups, students, and progress fetched for the current account. |
| Teacher authoring | Form structure and authoring controls. | Questions, rubrics, templates, students, AI-generated drafts, saved assignments, and server validation results. |
| Interview room | Consent wording, controls, layout, and supported session actions. | Interview/session status, current question, progress, recording duration, transcript, recording, upload result, analysis, and report state. Speech and camera states also depend on browser support and permission. |
| Reports | Report sections, chart/summary presentation, and review form. | Scores, analysis coverage, topic analysis, improvement plan, transcripts, teacher comments, score overrides, and export contents. |
| Admin | Account/report/settings page structure and available operations. | Accounts, class groups, settings, analytics, and report rows from the database. |
| Backend behavior | Route definitions, validation rules, scoring/report logic, authorization rules, and local Ollama adapter. | Database records and configured runtime values; local Ollama and faster-whisper availability, SMTP, and local/S3/R2 storage. |

The frontend does not contain interview assignments or user records as a fixed dataset. Those are fetched from the API. Browser speech synthesis and microphone/camera capture are client-side browser features; server-side analysis and persistence happen after an audio upload.

## 4. Main user flows

### Account creation and access

1. A user registers as a student or teacher and selects a course/class group.
2. The API validates the request and creates the account in `PENDING` status.
3. An admin activates or rejects the account.
4. Active users sign in. The frontend stores the returned bearer token and requests the current account profile.
5. Protected routes use the authenticated profile/role to show the appropriate dashboard. The backend independently checks authentication, role, and resource ownership on protected API requests.

Password reset uses a short-lived token delivered by SMTP when mail configuration is present.

### Teacher setup and assignment

1. The teacher creates or selects questions and rubrics.
2. Questions can be authored manually or drafted through the optional LLM integration. Drafts are reviewed before commit to the reusable question bank.
3. The teacher arranges questions and rubric links in an interview template.
4. The teacher assigns the template to one student or a class group, optionally with a scheduled date/time.
5. The backend creates interview records and copies the ordered template questions/rubrics into each assignment, preserving the assignment's interview content.
6. Scheduled assignments may be cancelled by the assigning teacher while they are still scheduled.

### Student interview and answer processing

1. The student opens an assigned interview. The frontend loads its session state and current question.
2. Before a scheduled interview starts, the student explicitly consents to audio recording. The browser checks microphone permission, then the API records consent and starts the interview.
3. The student starts the interview, listens to the spoken question if speech synthesis is supported, and records an answer with `MediaRecorder`.
4. The student can listen back, re-record, submit, skip the question, or finish the interview. The UI prevents duplicate starts/submissions while those operations are pending.
5. On submission, the backend validates ownership and the assigned current question, stores the recording under an immutable key, and commits a durable processing job. The student proceeds without waiting for transcription, audio analysis, or Ollama evaluation.
6. One local worker processes answer jobs sequentially. It stores transcription and audio analysis before evaluation, retries transient failures, and marks exhausted/unusable work for teacher review. Skipped and unanswered questions are also marked for review.
7. After the last question, the interview remains in `PROCESSING`. The report is finalized only after all accepted answer jobs are either evaluated or terminally marked for teacher review. Missing evaluations remain unavailable; they are never treated as zero.
8. The student and authorized teacher/admin can read the finalized report; teachers/admins can add review feedback and score overrides.

The answer endpoint waits only for recording storage and the database commit. The final processing screen waits for the persistent worker to finish or exhaust retries for every accepted answer.

### Report and review

1. The report API assembles answer data, transcript status, rubric evaluation, teacher review, interview-level score, and audio-analysis summaries.
2. The report screen displays available scores, analysis coverage, topic performance, feedback, improvement recommendations, and saved audio controls.
3. The assigned teacher or admin can provide an overall review and per-question feedback/score overrides.
4. PDF and Excel exports use the report data and include the product's learning/decision-support disclaimer.

## 5. Frontend route map

Routes are registered in `frontend/src/App.jsx`.

| Route | Access | Screen/purpose |
| --- | --- | --- |
| `/` | Public (signed-in users go to dashboard) | Marketing home page |
| `/login` | Public | Sign in |
| `/register` | Public | Student/teacher registration |
| `/pending` | Public | Pending account information |
| `/forgot-password` | Public | Request password reset |
| `/reset-password` | Public | Set password using reset token |
| `/dashboard` | Authenticated | Student, teacher, or admin dashboard based on role |
| `/rapidfire` | Student | Informal rapid-fire practice |
| `/interviews/:interviewId` | Student | Interview session |
| `/interviews/:interviewId/report` | Student, assigned teacher, or admin | Interview report and review |

Unknown paths redirect to the appropriate sign-in/dashboard destination. Backend authorization remains authoritative even when a frontend route is protected.

## 6. Backend API groups

All routes are under `/api`. The complete endpoint details and payload notes are in `README.md`; this is the functional grouping:

| Group | Main routes and purpose |
| --- | --- |
| Health | `GET /api/health` checks API/database availability and reports answer-worker health. |
| Authentication | `/auth/register`, `/auth/login`, `/auth/me`, `/auth/forgot-password`, `/auth/reset-password`. |
| Admin | `/admin/users`, `/admin/pending-users`, user status, courses/class groups, settings, analytics, and exports. |
| Teacher authoring | `/questions`, `/rubrics`, `/templates`; question drafting/commit; teacher analytics and student lookup. |
| Assignment/session | `/interviews` lists/creates assignments; `/interviews/:id` loads state; start, answer, advance, cancel, and authorized audio routes. |
| Reports | `/interviews/:id/report`, report review update, PDF/Excel export, and student progress. |

Authenticated calls use `Authorization: Bearer <token>`. The frontend's `api()` helper in `frontend/src/api.js` adds the token and JSON content type as appropriate, handles multipart `FormData` without overriding its content type, and converts failed responses into user-facing API errors.

## 7. Data model summary

The principal SQLAlchemy models are declared in `backend/queme/models.py`:

- **User** — account identity, role, status, and course/class-group association.
- **Department / Batch** — legacy internal model names used for courses and course/semester/academic-year groups.
- **QuestionBank** — reusable teacher questions and their topic/type/difficulty/expected points.
- **Rubric** — scoring criteria and maximum score, including seeded default rubrics.
- **InterviewTemplate / TemplateQuestion** — reusable ordered interview plans and question-to-rubric links.
- **Interview / InterviewQuestion** — student assignment and a snapshot of the questions/rubrics used by that assignment, plus current progress/status.
- **AudioAnalysis** — transcript status, transcript, audio quality, and communication measurements for an answer.
- **Report / QuestionReview** — interview summary and teacher review data/overrides.
- **SystemSetting** — configurable scoring weights.

Schema changes are tracked in `backend/migrations/versions/`. From `backend/` in Windows PowerShell or Linux Bash with the virtual environment activated, apply checked-in migrations with `python -m flask --app run.py db upgrade`.

## 8. Project structure

```text
QueMe/
├── README.md                         # Existing setup and API reference
├── README2.md                        # This implementation report
├── backend/
│   ├── run.py                         # Flask application entry point
│   ├── config.py                      # Environment-backed configuration/validation
│   ├── requirements.txt               # Python dependencies
│   ├── migrations/
│   │   ├── env.py                     # Alembic configuration
│   │   └── versions/                  # Checked-in schema migrations
│   ├── queme/
│   │   ├── __init__.py                # App factory, error handlers, health and seed command
│   │   ├── extensions.py              # SQLAlchemy and migration extensions
│   │   ├── models.py                  # Database models
│   │   ├── authz.py                   # Authentication/authorization helpers
│   │   ├── academics.py               # Course/class-group utilities
│   │   ├── api_errors.py              # API error and JSON helpers
│   │   ├── blueprints/
│   │   │   ├── auth.py                # Registration, login, reset flows
│   │   │   ├── admin.py               # Administration and campus analytics
│   │   │   ├── teacher.py             # Authoring, templates, assignments
│   │   │   ├── session.py             # Student interview and audio submission
│   │   │   └── reports.py             # Reports, review, progress and exports
│   │   ├── services/
│   │   │   ├── audio_analysis.py      # Audio metrics, quality, and intent detection
│   │   │   ├── transcription.py       # faster-whisper adapter
│   │   │   ├── llm.py                 # Optional LLM integration
│   │   │   ├── storage.py             # Local, S3, and R2 audio storage
│   │   │   └── reports.py              # Evaluation, analytics, PDF/Excel building
│   └── tests/
│       └── test_interview_flow.py     # Backend interview workflow tests
└── frontend/
    ├── index.html                     # Vite document entry
    ├── package.json                   # Scripts and JS dependencies
    ├── vite.config.js                 # Dev server and /api proxy
    ├── tailwind.config.js             # Tailwind theme/content config
    ├── postcss.config.js              # CSS processing configuration
    └── src/
        ├── main.jsx                   # React bootstrap, router, auth provider, global CSS
        ├── App.jsx                    # Routes, shared screens, interview room, reports
        ├── TeacherDashboard.jsx        # Teacher workspace UI
        ├── auth.jsx                   # Auth context and persisted session handling
        ├── api.js                     # Authenticated API request helper
        └── styles.css                 # App styles and responsive layout
```

Generated directories such as `frontend/node_modules`, `frontend/dist`, Python virtual environments, caches, and uploaded recordings are runtime/build artifacts rather than application source. The tree above lists source files relevant to the implemented application.

## 9. Development Setup & Running Commands

QueMe supports Windows and Linux. The full setup, daily startup, health checks, logs, shutdown, and migration instructions for both systems are in [README.md - Development Setup & Running Commands](README.md#development-setup--running-commands).

Use 64-bit Python 3.11 (the compatibility workflow covers 3.10-3.12) and Node.js 22. Create a fresh Python environment and install `backend/requirements.txt` on each machine. Activate it with `./.venv/Scripts/Activate.ps1` in Windows PowerShell or `source .venv/bin/activate` in Linux Bash, from `backend/`. Virtual environments and `node_modules` are specific to the operating system.

Copy `backend/.env.example` to the root `.env` if one does not exist, then set `SECRET_KEY`, `ADMIN_EMAIL`, and `ADMIN_PASSWORD`. Root `.env` takes precedence over `backend/.env`; process environment variables take precedence over both. The default database is `backend/queme.db`, and PostgreSQL is optional through `DATABASE_URL`. Relative storage and log directories resolve from `backend/`. Use destination-specific absolute paths when moving between systems.

With the backend environment active, these commands work on both platforms:

```text
python -m pip install -r requirements.txt
python -m flask --app run.py db upgrade
python -m flask --app run.py seed
```

Install Ollama separately using its Windows application or [Linux installation instructions](https://docs.ollama.com/linux). Start its server/service, then run `ollama pull qwen3:1.7b` (or your configured model). Transcription uses CPU/int8 on both systems; no CUDA is required for transcription.

For daily development, run the following in separate terminals:

| Component | Directory | Command (backend environment active where applicable) |
| --- | --- | --- |
| Answer worker | `backend/` | `python -m flask --app run.py process-answer-jobs` |
| API | `backend/` | `python -m flask --app run.py --debug run` |
| Frontend | `frontend/` | `npm run dev` (run `npm ci` once first) |

The API defaults to port 5000. Vite defaults to 5173 and proxies `/api` to the backend. Waitress is included as the shared Windows/Linux WSGI server; see the README for its API startup command. Gunicorn is installed only on non-Windows systems. Run one answer worker per installation, on a single host; its OS lock does not coordinate multiple hosts. Press Ctrl+C to stop foreground processes.

Run `python -m unittest discover -s tests -v` from `backend/` and `npm run build` from `frontend/`. The compatibility workflow checks both Windows and Ubuntu, including real process locks and native audio decoding without model downloads. Check live API/worker health at `http://127.0.0.1:5000/api/health`.

Microphone access requires a supported browser and a secure context (localhost is accepted). Available speech-synthesis voices vary by system/browser. Local AI requires Ollama and the configured model; transcription, email, S3, and R2 depend on runtime configuration and service availability. Local storage is the default; configure private object storage explicitly if desired.

## 10. Current implementation boundaries

- The active backend environment now uses `backend/queme.db` (SQLite), and its schema plus baseline admin/course/rubric data have been initialized locally. The previous cloud database was not reachable and its records were not copied.
- S3 is selected for audio, but the AWS key values are currently blank and bucket existence/access have not been verified. Audio uploads will fail until valid AWS credentials are configured and the bucket is available.
- Automated question drafting, answer evaluation, and follow-up generation use only the configured local Ollama server. If it is unavailable, the interview can still complete and the report flags the answer for teacher review. No external LLM provider is used as a fallback.
- Interview reports aggregate saved per-question results; the current application does not make an additional LLM call for an interview-level narrative summary. Adaptive difficulty is not currently part of the interview-session flow.
- Transcription and audio analysis depend on the configured `faster-whisper` model/runtime. A missing or unusable transcript can result in teacher-review status.
- Answer transcription, audio analysis, and evaluation run through a persistent single-worker queue after the recording and job are committed. The API exposes processing status through the authenticated interview session.
- Camera support is an optional local preview, not a recorded video interview feature.
- `frontend/src/App.jsx` currently contains several page components and the interview-room flow; `TeacherDashboard.jsx` is separated as a dedicated dashboard module. The current project has no standalone `useAudioRecorder` hook.
- This report documents source behavior and configuration. It does not claim that external services, secrets, database contents, or a deployment environment are currently available.
