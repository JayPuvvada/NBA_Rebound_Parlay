# NBA Rebound Projection Model

## Installation
```bash
pip install -r requirements.txt
```

## Usage
Run the `main.py` script with the player name and opponent team abbreviation.

### Basic Example
Predict Nikola Jokic vs Boston:
```bash
python3 main.py "Nikola Jokic" BOS
```

### With Betting Line and Context
Check probability of Jokic going OVER 12.5 rebounds, playing AWAY:
```bash
python3 main.py "Nikola Jokic" BOS --line 12.5 --away
```

### Team Fit Check (Cannibalization)
Verify if individual projections fit within the team's total capacity:
```bash
python check_team_fit.py DEN ORL
```
*(Arguments: Team Abbreviation, Opponent Abbreviation)*
