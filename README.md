# Questline

Questline is a project management application designed for workflows that require more than just a simple task list. It provides a structured environment where you can organize work into Hubs, manage progression through Stages, and track high-level Quests alongside individual Objectives.

## Walkthrough

![Questline walkthrough](./fresh-canvas-walkthrough.gif)

## Terminology

To get the most out of Questline, it is helpful to understand how work is organized:

*   **Hubs**: The top-level containers for your projects. Each Hub represents a specific area of focus or a complete project board.
*   **Stages**: The columns within a Hub that represent the status or category of work (e.g., Backlog, In Progress, Review).
*   **Objectives**: Individual items of work. These are the cards you move between Stages.
*   **Quests**: High-level objectives that act as parents to other tasks. When an objective is designated as a Quest, it can spawn and track multiple sub-objectives.
*   **Log Stages**: Special read-only columns that use dynamic filters to show a live feed of objectives from across the entire Hub based on specific criteria.

## Features

Questline includes several advanced features to help you manage complex workflows:

*   **Customizable Hubs**: Create multiple workspaces and define your own Stages to match your specific process.
*   **Objective Types and Templates**: Set up blueprints for different kinds of work to ensure that every objective has the right metadata and default settings.
*   **Flexible Custom Fields**: Extend your objectives by adding specialized data fields like text, numbers, dates, or dropdown menus based on the objective type.
*   **Automation Engine**: Create rules that automatically perform actions based on specific triggers. For example, you can set a rule to move an objective to a specific Stage whenever it is marked as completed.
*   **Checklist Spawning**: Break down Quests into smaller objectives using checklists. Checklist items can be converted into standalone objectives that remain linked to their parent Quest.
*   **Dynamic UI**: A responsive design with drag-and-drop capabilities and rich browser-side interactions for a smooth management experience.

## Technology Stack

The project is built using a modern Python-based stack:

*   **Backend**: Developed with FastAPI for high performance and type safety.
*   **Database**: Uses SQLAlchemy for database interactions, with SQLite as the default storage engine.
*   **Frontend**: Utilizes Jinja2 for server-side rendering, combined with standard JavaScript and CSS for a dynamic user interface.
*   **Validation**: Leverages Pydantic for robust data validation and schema management.

## Getting Started

### Prerequisites

To run this project, you will need:
*   Python 3.9 or higher
*   The `pip` package manager

### Installation

1.  Clone the repository to your local machine.
2.  Install the necessary dependencies using the provided requirements file:
    ```bash
    pip install -r requirements.txt
    ```
3.  Start the development server using uvicorn:
    ```bash
    uvicorn main:app --reload
    ```
4.  Access the application at `http://127.0.0.1:8000` in your web browser.

## Project Structure

*   `main.py`: Contains the core application logic, API endpoints, and the automation engine.
*   `models.py`: Defines the database schema and SQLAlchemy models.
*   `database.py`: Handles the database connection and session management.
*   `templates/`: Stores the Jinja2 HTML templates for the frontend.
*   `static/`: Contains static assets, including CSS and client-side logic.
*   `tests/`: Includes the suite of unit and integration tests to ensure application stability.

## Deployment Notes

For internet exposure, run Questline behind HTTPS at a reverse proxy such as nginx. Configure HSTS at the proxy edge, not in the application, and set `QUESTLINE_TRUSTED_PROXIES` to the proxy addresses that connect directly to the app.

See [`docs/deployment.md`](docs/deployment.md) for deployment guidance and recommended production environment settings.
