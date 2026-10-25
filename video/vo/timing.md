| Scene | Start | End | Line | Note |
|---|---|---|---|---|
| 1 Problem | 0.30 | 1.18 | Imagine this. |  |
| 1 Problem | 1.54 | 4.38 | An earthquake strikes and a building is severely damaged. |  |
| 1 Problem | 4.72 | 6.08 | People are trapped inside. |  |
| 1 Problem | 6.39 | 7.96 | But nobody knows where they are. |  |
| 1 Problem | 8.30 | 12.20 | Rescue teams arrive. They need to find those people, and they need to find them FAST. |  |
| 1 Problem | 12.91 | 13.77 | But there's a problem. |  |
| 1 Problem | 14.33 | 15.80 | Nobody knows what's inside. |  |
| 1 Problem | 16.09 | 18.83 | And every second spent searching could mean a life lost. |  |
| 2 Existing limitations | 19.30 | 24.85 | Today, rescue teams use a big, bulky, specialized drone to search dangerous buildings. |  |
| 2 Existing limitations | 25.36 | 28.55 | But mapping an entire building with just one drone is SLOW, |  |
| 2 Existing limitations | 28.74 | 30.12 | these drones are EXPENSIVE, |  |
| 2 Existing limitations | 30.30 | 32.74 | and teams often have just ONE or TWO available. |  |
| 2 Existing limitations | 32.89 | 35.01 | It also takes time that victims do not have. |  |
| 3 Breakthrough | 36.30 | 37.66 | So we asked ourselves... |  |
| 3 Breakthrough | 38.02 | 41.19 | What if we could search an ENTIRE building... in a fraction of the time? |  |
| 3 Breakthrough | 42.04 | 42.96 | Not with ONE drone. |  |
| 3 Breakthrough | 43.34 | 44.02 | Not with TWO. |  |
| 3 Breakthrough | 44.34 | 47.89 | But with an ENTIRE SWARM of small, affordable drones that FLY THEMSELVES! |  |
| 3 Breakthrough | 49.04 | 50.12 | Introducing SWARM! |  |
| 4 How Swarm works | 50.80 | 54.57 | Our swarm spreads out, searching different parts of the building AT THE SAME TIME! |  |
| 4 How Swarm works | 54.90 | 56.79 | No need for someone to fly each drone. |  |
| 4 How Swarm works | 57.02 | 60.15 | And everything they see comes together into ONE LIVE 3D MAP! |  |
| 4 How Swarm works | 60.39 | 62.53 | It shows rescuers where people are trapped, |  |
| 4 How Swarm works | 62.84 | 65.20 | in fact, it tracks their vitals using Presage, |  |
| 4 How Swarm works | 65.46 | 66.98 | it shows where paths are blocked, |  |
| 4 How Swarm works | 67.20 | 68.44 | and where danger lies. |  |
| 5 Advantages | 69.80 | 71.43 | Here's what changes. We now have: |  |
| 5 Advantages | 71.80 | 74.78 | FASTER SEARCHES! Because many drones explore at once. |  |
| 5 Advantages | 75.01 | 79.89 | LOWER COSTS! Because we use small, affordable drones sharing one powerful computer. | runs 0.01s into next cue |
| 5 Advantages | 79.93 | 83.13 | AND NO PILOT FOR EVERY DRONE! Because they are autonomous. |  |
| 6 Research | 84.30 | 85.65 | And research backs this up! |  |
| 6 Research | 85.98 | 92.88 | A 2024 study published in Sensors found that collaborative robots reduced indoor mapping time by nearly 50%! |  |
| 6 Research | 93.15 | 97.48 | On the other hand, specialized drones can cost way up to $30,000 EACH! |  |
| 7 Homepage | 98.60 | 101.03 | But enough talking. Let's dive into the demonstration! |  |
| 7 Homepage | 101.23 | 106.73 | We've turned this idea into a platform designed to make search-and-rescue operations faster, safer, and smarter. |  |
| 8 Homepage scroll | 107.90 | 114.03 | From sending out autonomous drones to tracking their progress, everything is designed to help rescue teams act quickly. |  |
| 8 Homepage scroll | 114.46 | 117.81 | And the best part? Rescuers can manage everything from one place. |  |
| 9 Mission mode | 118.90 | 120.41 | So, let's see it in action! |  |
| 10 Create mission | 121.90 | 124.64 | First, we select the building and the type of emergency. |  |
| 11 Launch | 126.90 | 129.81 | And with one click, we launch our FOUR autonomous drones! |  |
| 12 Dashboard | 131.90 | 134.95 | Now, this is where the rescue team monitors the entire mission! |  |
| 13 Four feeds | 136.20 | 140.80 | Here, you can see all four drones exploring different parts of the building AT THE SAME TIME! |  |
| 14 3D map | 142.00 | 148.19 | And everything they see comes together into ONE live 3D map, showing the building's layout and how much we've explored! |  |
| 15 Survivor | 149.00 | 151.42 | And look! We've detected a potential survivor! |  |
| 15 Survivor | 151.77 | 155.13 | We can even see their estimated breathing rate and pulse using Presage! |  |
| 16 Hazards | 156.60 | 163.25 | As we scroll, we can also see dangers detected along the way, like blocked passages, closed doors, and gas cylinders! |  |
| 17 Crew | 164.40 | 165.65 | And here's the best part! |  |
| 17 Crew | 165.85 | 170.10 | We can send this information directly to the rescue crew, helping them decide where to go! |  |
| 18 Handoff | 171.20 | 173.55 | But how does all of this work behind the scenes? |  |
| 18 Handoff | 173.79 | 175.71 | Here's our technical team to explain! |  |
| C1 Hardware | 176.60 | 184.04 | Each drone is a cheap E58 quadcopter. An ESP32-S3 relay streams its camera over Wi-Fi to one GPU computer. |  |
| C2 Brain | 184.24 | 189.98 | Our Rust and CUDA core fuses every view into one shared 3D map, and plans each drone's next move. |  |
| C2 Brain | 190.18 | 192.99 | YOLO26 spots people, doors and fire. |  |
| C3 Console | 193.19 | 199.83 | It all syncs through SpacetimeDB to the console. The full swarm runs in our simulator; our real drone streams live today. |  |
| C4 Roadmap | 200.03 | 204.04 | Next: real swarm flights, and robots like Boston Dynamics Spot. |  |
| D Closing | 204.60 | 205.97 | When lives are on the line... |  |
| D Closing | 206.62 | 207.66 | EVERY SECOND COUNTS! |  |
| D Closing | 208.32 | 209.47 | SWARM. SEND THE SWARM! |  |
