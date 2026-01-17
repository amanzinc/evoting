# Ballot Marking Device - E-Voting Prototype

This project is a Python-based prototype for a Ballot Marking Device (BMD), designed to demonstrate a secure, user-friendly, and verifiable electronic voting system.

## Project Goals

1.  **Transparency**: Open-source implementation of voting logic.
2.  **Flexibility**: Dynamic candidate loading from external configuration files.
3.  **Auditability**: Secure text-based logging of every vote cast for verification.
4.  **Accessibility**: User interface designed for clarity and ease of use, supporting both single-choice and preferential (ranked) voting modes.

## Features

- **Dynamic Candidate Loading**: Candidates are loaded from a `candidates.csv` file, allowing for easy updates without changing the code.
- **Vote Logging**: Every vote is logged to `votes.log` with a precise timestamp, voting mode, and candidate details.
- **Dual Voting Modes**:
    - **Normal Voting**: Standard single-choice selection.
    - **Preferential Voting**: Ranked choice voting (select 1st, 2nd, 3rd preference).
- **Dynamic UI**: The interface automatically adjusts its layout based on the number of candidates.
- **NOTA Support**: "None of the Above" is included as a standard option.

## Project Layout

- `ui_prototype.py`: The main application script containing the UI and voting logic.
- `candidates.csv`: Configuration file defining the list of candidates.
- `votes.log`: The output log file where votes are recorded (created after the first vote).
- `functional_spec.md`: Detailed functional specifications for the system.
- `requirements.txt`: Python dependencies.

## Setup and Usage

### Prerequisites
- Python 3.x installed on your system.
- `tkinter` support (usually included with Python on Windows/macOS; on Linux: `sudo apt-get install python3-tk`).

### Running the Application

1.  Clone the repository or download the files.
2.  Open a terminal in the project directory.
3.  Run the application:
    ```bash
    python ui_prototype.py
    ```

### Configuring Candidates

To update the list of candidates, edit the `candidates.csv` file.
**Format**: `id,name,party`

Example:
```csv
id,name,party
1,Narendra Modi,Bharatiya Janata Party (BJP)
2,Rahul Gandhi,Indian National Congress (INC)
6,New Candidate,New Party
```
*Note: ID 0 must be reserved for NOTA, which is handled internally.*

## License
[License Information Here]
