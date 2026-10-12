## Data
A user account is stored for each person, but in a final version of the product individual user data would be encrypted and not available to other users. The data associated with each account will be vehicle battery capacity, current charging location, a user ID (email or phone number) and password, and other vehicle information.

The reinforcement learning algorithm uses energy cost data based on location and the total number of cars plugged into a charging station at a given time.

## Users and Markets
The data represents location and energy costs, which could inadvertently vary based on socioeconomic factors that we are not considering.

Data could be skewed by income/wealth in an area (which could correlate to more chargers since installation of chargers requires wealth and electric cars are expensive), or by government spending -- which districts get money to install chargers. Also consider urban/rural where chargers may be far away and electricity must be spent getting to/from the charging station. 

Also think about infrastructure -- a poorer area will have lower use of chargers if electric cars are expensive, but also may have less updated infrastructure that is more likely to be broken if it is rarely used or serviced. A wealthier area will have higher usage rates and visibility but could have more worn down infrastructure from more use.

## Rules
Any general data collection rules, could vary by state or country of use so the product would need to evolve to fit the location.

## Fix
If we get to making a map or list of prices by location, add an overlapping map of wealth to see if there are trends to detect about charging pricing in certain areas. Try to read a study on electric cars and charging infrastructure in underserved communities vs not.
