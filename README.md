# pyro-devops

Deployment and infrastructure management

  

## Getting started

## Structure

The file docker-swarm.yml is used for the docker swarm
The folder nginx is a demo for a image of a reverse proxy with nginx 

### Prerequisites

  
- Docker swarm

  

### Installation

https://docs.docker.com/get-docker/

https://docs.docker.com/engine/swarm/swarm-tutorial/create-swarm/

  
## Security good practice
https://docs.docker.com/engine/install/linux-postinstall/
Log your infrastructure and your containers (portainer,...) 
Run your ssh/administration on a private network (with bastion + vpn)
https://www.stackrox.com/post/2019/09/docker-security-101/
AppArmor/ SELinux,failtoban, iptable, waf
Check your SLA, IT Disastery Recovery process
Vulnerability assessment and management (VAM)
Identity and Access Management

## Usage




Export the variables/secret in your env file (if you don't have a Vault) 
```
export BUCKET_MEDIA_FOLDER=media
...
```
  
If needed build your images (for exemple the mynginx image in the folder nginx) and push it in the local registry

```
docker run -d -p 5000:5000 --restart=always --name registry registry:2 #start the local registry

docker build -t pyro/mynginx .

docker image tag pyro/mynginx localhost:5000/mynginx

docker push localhost:5000/mynginx:latest

docker pull localhost:5000/mynginx
```

and after deploy your docker swarm
```

docker stack deploy -c docker-swarm.yml my_node

```

You can check that the service is running with



```

docker service ls

docker ps

docker service logs xxxxxx

```