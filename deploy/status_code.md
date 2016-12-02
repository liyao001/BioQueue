## CPBQueue Status Code

This file describes status code used in CPBQueue.

| status code| code description                    |
|:----------:|:-----------------------------------:|
| 0          | Waiting, not in job queue           |
| >0         | Running, the number is the n-th step|
| -1         | Completed                           |
| -2         | Waiting at check point              |
| -3         | Error occured                       |

| learning code | code description |
|:-------------:|:----------------:|
| 1             | Disk usage       |
| 2             | Memory usage     |
| 3             | CPU usage        |