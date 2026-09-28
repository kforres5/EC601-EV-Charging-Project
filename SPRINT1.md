## Mission
For an electric vehicle owner who is charging their vehicle often and is looking to save money on charging costs, the Decentralized EV Charging using a multi-agent reinforcement learning system is a optimization method that uses RL to optimize charging cost while protecting data from individual EVs. Unlike what is done today, where most drivers plug into home, workplace, or public chargers with no optimization scheme present, it allows EV owners to harness technological advances to save money and optimize energy usage.

## Target User
EV Owner: As the EV Owner, I want to have my car fully charged at the cheapest possible rate so that I can save money and have it ready when I want to use it.

## User Stories
- As a user, I'd like to know how much EverSource charges on average per month
- As a user, I'd like to know how much I spend on average per month without any optimization
- As a user, I'd like to know how my vehicle charging performance/cost compares to nearby surrounding charging vehicles

## Feasibility
We will use data from Eversource about energy pricing: https://www.eversource.com/clp/vpp/vpphistory.aspx
We are using the year of July 2025 - June 2026 for a sample.

## Tooling

## Demo Sentence
At the end of two weeks we will show the project skeleton, which means setting up a framework of modules (outlined in the diagram) that each separately work as intended.

## Assumptions

## Evaluation and Baseline
Compared to the standard charging infrastructure used in homes, workplaces, and public fast-chargers today, the optimization scheme saves a few dollars every charge, which can add up to a few hundred dollars a year saved on charging costs.

## Merged Research

## Potential Harm
This project is intentionally scoped to avoid the two riskiest failure modes of simulation-heavy robotics/AI projects: (1) no dependency on integrating multiple external simulators (CARLA, SUMO, Gazebo), since the environment is custom-built and lightweight; (2) no dependency on training a from-scratch deep perception model. The main risks are standard RL training risks — reward shaping and convergence — which can be mitigated by starting with a small N and simple reward function, then scaling up once the pipeline is validated end-to-end.

