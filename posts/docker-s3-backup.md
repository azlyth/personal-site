---
title: "A simple image to backup volumes to S3"
date: '2016-10-21'
draft: false
---
One part of setting up my online presence naturally includes getting backups going.

Since I'm trying to keep everything containerized, I did some research into what Amazon S3 backup
solutions are out there. I found a popular project called {{< link "dockup" "https://github.com/tutumcloud/dockup" >}}
that basically does everything I wanted to have done.

However, upon looking at what I had to configure, I thought it could be simpler.

## How dockup works

In order to get **dockup** working, you have to mount the volumes you want to backup to some
arbitrary place in the filesystem, and provide the following environment variables:

- AWS\_ACCESS\_KEY\_ID
- AWS\_SECRET\_ACCESS\_KEY
- AWS\_DEFAULT\_REGION
- BACKUP\_NAME
- PATHS\_TO\_BACKUP
- S3\_BUCKET\_NAME

So, in English, given a bunch of directories (specified in PATHS\_TO\_BACKUP), **dockup** will
create a timestamped backup (using the name BACKUP\_NAME) in the bucket S3\_BUCKET\_NAME.

## I'd do it a bit differently

My ideal backup image would work different in a few ways.

First, I want a separate backup for each of my apps. At any given time, I'm not sure which services
I will be running. Maybe I'll stop the blog and keep the git repo running. Or maybe I'll add a new
service. I want to keep the data for each of those services separate.

Next, I shouldn't have to specify which directories I want to backup. I could just put my volumes
somewhere specific, like **/backups**.

Finally, the structure of the backup directory can contain the bucket and name. For example, any
data in the directory **/backups/app-backups/blog-data** will be bundled and named **blog-data**
and placed in the **app-backups** bucket.


## So I made my own

With those ideas in mind, I made my own image called **s3-backup**. The following block is now live
in my Docker Compose file:

```yaml
  backups:
    image: ptrvldz/s3-backup:0.1
    container_name: backups
    restart: always
    volumes:
      - ghost:/backups/ptrvldz-backups/ghost-blog
      - gogs:/backups/ptrvldz-backups/gogs
    environment:
      - AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
      - AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
      - AWS_DEFAULT_REGION=$AWS_DEFAULT_REGION

```

All I have to do is provide my AWS credentials and put my volumes in the right places. With this
setup, the two following backups are placed in my **ptrvldz-backups** bucket:

- ghost-blog/ghost-blog-TIMESTAMP.tar.bz2
- gogs/gogs-TIMESTAMP.tar.bz2

You can find **s3-backup** on {{< link "GitHub" "https://github.com/azlyth/docker-s3-backup" >}} and
{{< link "Docker Hub" "https://hub.docker.com/r/ptrvldz/s3-backup/" >}}.
