# Functional Specification Document (FSD)
**Project Name:** Ballot Marking Device (BMD)
**Version:** 1.0
**Date:** 2026-01-17
**Author:** Aman Gupta

---

## 1. Introduction
### 1.1 Purpose
The purpose of this document is to define the functional requirements for the Ballot Marking Device (BMD). This device is intended to enable voters to verify their eligibility via an RFID token, cast their vote using a touch screen interface, and receive physical confirmation of their vote via a VVPAT and receipt.

### 1.2 Scope
The BMD will:
*   Read voter eligibility and ballot configuration from initial RFID token scan.
*   Retrieve a specific or random ballot configuration from the local database based on the token data.
*   Allow the voter to select candidates, supporting preferential voting methods.
*   Print a VVPAT (Voter Verifiable Paper Audit Trail) for audit purposes.
*   Print a receipt for the voter.
*   Store cast votes securely in the device's local storage.
*   Allow election officials to extract vote data at the conclusion of the election.

## 2. General Description
### 2.1 Product Perspective
The BMD is a standalone hardware kiosk deployed at polling stations. It operates independently of the internet during the voting session to ensure security. It interfaces physically with voters via a touchscreen, an RFID reader, and a printer.

### 2.2 User Characteristics
*   **Voter:** The primary user. Includes individuals of varying technical literacy and physical abilities.
*   **Election Official:** Responsible for device setup, maintenance during polling, and data extraction at close of polls.

### 2.3 General Constraints
*   **Security:** The device must be tamper-proof and ensure vote secrecy.
*   **Offline Operation:** Critical functions must not rely on network connectivity.
*   **Accuracy:** 100% accuracy in recording user intent is required.

## 3. Functional Requirements

### 3.1 Feature: RFID Authentication & Initialization
*   **Description:** The session begins when a voter scans their RFID token.
*   **Inputs:** RFID Token (ISO 14443 or similar).
*   **Processing:**
    1.  Read token data.
    2.  Validate token digital signature.
    3.  Extract ballot ID or constituency information.
*   **Outputs:**
    *   Success: Load Voting Interface.
    *   Failure: Display "Invalid Token" error.

### 3.2 Feature: Ballot Retrieval
*   **Description:** Determining which ballot to display to the user.
*   **Inputs:** Token Data (Constituency/Ballot ID).
*   **Processing:**
    1.  Query local database for the corresponding ballot template.
    2.  *Requirement:* Fetch a random ballot permutation from the database (as per specification) to prevent pattern voting or for randomized candidate ordering.
*   **Outputs:** Ballot data structure ready for rendering.

### 3.3 Feature: Voting Interface (Touch Screen)
*   **Description:** The interactive screen where voters make their choices.
*   **Inputs:** User touch gestures.
*   **Processing:**
    1.  Render candidate list.
    2.  Handle selection toggle.
    3.  Support **Preferential Voting**: Allow user to rank candidates (1, 2, 3...) if required by the ballot type.
    4.  Validate "Vote" command (check for under-votes/over-votes).
*   **Outputs:** Visual feedback of selected candidates/rankings.

### 3.4 Feature: Vote Casting & Output
*   **Description:** Finalizing the vote and generating physical records.
*   **Inputs:** "Confirm Vote" button press.
*   **Processing:**
    1.  Commit vote data to encrypted local storage.
    2.  Generate print command.
*   **Outputs:**
    *   **VVPAT:** A printed paper record displayed behind glass for voter verification.
    *   **Receipt:** A separate printed slip provided to the voter.
    *   **Screen:** "Vote Cast Successfully" message.

### 3.5 Feature: Data Extraction & Election Close
*   **Description:** retrieving results after the election.
*   **Inputs:** Administrator RFID card + PIN.
*   **Processing:**
    1.  Authenticate Administrator.
    2.  Decrypt vote storage.
    3.  Export vote tallies and logs.
*   **Outputs:** CSV/JSON data file to external USB storage.

## 4. Interface Requirements
### 4.1 User Interfaces
*   **Voter UI:** Simple, high-contrast buttons. Large fonts. clear "Next", "Back", and "Cast Vote" navigation.
*   **Admin UI:** Hidden menu accessible via special key combination or specific RFID card.

### 4.2 Hardware Interfaces
*   **RFID Reader:** Integrated bezel-mounted reader.
*   **Touch Screen:** Capacitive touch panel.
*   **Printer:** Thermal printer with cutter for Receipts; internal spooler for VVPAT.
*   **Data Port:** Secure USB port for initial configuration and final data extraction.

### 5. Non-Functional Requirements
### 5.1 Security
*   **Encryption:** AES-256 for all stored vote data.
*   **Auditability:** Every system event (not vote choice) is logged with a timestamp.

### 5.2 Reliability
*   **Power:** Battery backup to allow completion of current vote in case of power loss.
*   **Durability:** Screen must withstand 10,000+ touches per election cycle.
