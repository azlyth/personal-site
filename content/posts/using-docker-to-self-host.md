---
title: "Anatomy of this site's Docker Compose file"
date: 2016-10-17
draft: false
---
As it stands, this server has two services running: a blog and git repository. They're both routed
to by an nginx proxy, and my free SSL certificates are provided by the oh-so-wonderful Let's Encrypt.

The best part is that all of that is defined in and deployed by using a single Docker Compose file.

That means the only thing I had to do on my server was install
{{< link "Docker" "https://www.docker.com/what-docker" >}} (which is made easy by
{{< link "Docker Machine" "https://docs.docker.com/machine/overview/#/what-is-docker-machine" >}}).
The rest happens inside containers that play well with each other thanks to
{{< link "Docker Compose" "https://docs.docker.com/compose/overview/#/overview-of-docker-compose" >}}.

I'm going to explain the file section by section, but first, here's all of it:

```yaml
version: '2'

services:

  nginx-proxy:
    image: jwilder/nginx-proxy:0.4.0
    container_name: nginx-proxy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - certs:/etc/nginx/certs:ro
      - /etc/nginx/conf.d
      - /etc/nginx/vhost.d
      - /usr/share/nginx/html
      - /var/run/docker.sock:/tmp/docker.sock:ro
    environment:
      - DEFAULT_HOST=ptrvldz.me

  letsencrypt-nginx-proxy:
    image: jrcs/letsencrypt-nginx-proxy-companion
    container_name: letsencrypt-nginx-proxy
    volumes_from:
      - nginx-proxy
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - certs:/etc/nginx/certs:rw

  blog:
    image: ghost:0.11.2
    container_name: blog
    volumes:
      - ghost:/var/lib/ghost
    environment:
      - VIRTUAL_HOST=ptrvldz.me
      - LETSENCRYPT_HOST=ptrvldz.me
      - LETSENCRYPT_EMAIL=webmaster@ptrvldz.me

  git:
    image: gogs/gogs:0.9.97
    container_name: git
    volumes:
      - gogs:/data
    environment:
      - VIRTUAL_HOST=git.ptrvldz.me
      - VIRTUAL_PORT=3000
      - LETSENCRYPT_HOST=git.ptrvldz.me
      - LETSENCRYPT_EMAIL=webmaster@ptrvldz.me

volumes:

  ghost:
    external: false
  gogs:
    external: false
  certs:
    external: false
```

## Version

The first line defines which Docker Compose file format we're going to write. The recommended
format is the newer format, so we start the file with:

```yaml
version: 2
```

## Services

Next we get to the meat of the file, where we define our services. We begin our service definitions
with the line:

```yaml
 services:
```

And away we go.

## Service: nginx proxy

The nginx-proxy image is one of the most magical of them all.

Let's consider a usual desired setup: you want to host various web apps on different subdomains on
a single server. The way we typically solve this is by running a web server that forwards requests
to the desired applications.

There is usually a bunch of boilerplate involved in getting this going, but in essence, you're just
mapping a domain to some local port where your app is running.

The nginx-proxy image removes the boilerplate. Once running, it finds any containers that have the
**VIRTUAL_HOST** environment variable, and then forwards any requests bound for the domain defined by
the variable to that container.

In other words, if we start a WordPress container with the environment variable **VIRTUAL_HOST** set
to **wordpress.somesite.com**, then the nginx proxy will forward all requests for
**wordpress.somesite.com** to that WordPress container.

So let's look at the definition of the nginx-proxy:

```yaml
  nginx-proxy:
    image: jwilder/nginx-proxy:0.4.0
    container_name: nginx-proxy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/tmp/docker.sock:ro
      - certs:/etc/nginx/certs:ro
      - /etc/nginx/conf.d
      - /etc/nginx/vhost.d
      - /usr/share/nginx/html
    environment:
      - DEFAULT_HOST=ptrvldz.me
```

The first line is the name of our service. We then define which image we want to use and what we
want to call the container when it's running.

Because this is a web server that will be SSL-enabled, we specify that we want our actual
"hardware" server's port 80 and 443 to be forwarded to our nginx proxy.

We then define our various volumes. First, we give the container access to our host Docker socket
because that's how it will gather data about other containers. We then use a named volume
(identifiable by the slash-less string before the colon) for the SSL certificates because that's
where our letsencrypt container will place them. And then the remaining three volumes are defined
so that our letsencrypt container can write to the files in there.

Finally, we define the environment variable **DEFAULT_HOST** so the proxy knows which domain is
default, in case a request does not ask for a specific domain.


## Service: SSL certificate generation

If you've not yet heard of it, Let's Encrypt is a great project that allows you to get free SSL
certificates. With the easy-to-use clients that exist, it's all pretty much automatic.

And if you're using nginx-proxy, it's even easier. All we give our letsencrypt container is:

- access to our nginx-proxy volumes
- the Docker socket so it can see which services need a certificate
- a place to put the certificates

Let's look at the service definition:

```yaml
  letsencrypt-nginx-proxy:
    image: jrcs/letsencrypt-nginx-proxy-companion
    container_name: letsencrypt-nginx-proxy
    volumes_from:
      - nginx-proxy
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - certs:/etc/nginx/certs:rw
```

The first three lines again define the name of the Docker Compose service, the image we're using,
and the name of the running container.

We then specify that we want it to have access to the volumes that we created for our
nginx-proxy.

And finally, we give it access to the Docker socket and tell it to use a named volume for the
certs. Note that the named volume here (**certs**) is the same as the named volume being accessed by
the nginx-proxy.

## Service: Blog

We finally get to an actual application, a blog.

I knew I didn't want to use something heavy like Wordpress. And I love static-site generators, but
I have to spend some time thinking about a setup.

So I went with a compromise: Ghost. I can self-host it, and posts are written in Markdown, so I can
port to some static-site generation setup with ease later.

So now that all our preparation was done in the previous service definitions, let's see how we can
define our Ghost blog:

```yaml
  blog:
    image: ghost:0.11.2
    container_name: blog
    volumes:
      - ghost:/var/lib/ghost
    environment:
      - VIRTUAL_HOST=ptrvldz.me
      - LETSENCRYPT_HOST=ptrvldz.me
      - LETSENCRYPT_EMAIL=webmaster@ptrvldz.me
```

Again, the first three lines are the Docker Compose service name, the image that we'll be using,
and container name.

We then define a named volume for our data because we want our blog data to exist even if we
recreate this container.

And now the magic.

- By setting **VIRTUAL_HOST** to **ptrvldz.me**, our nginx-proxy will know to forward requests for
**ptrvldz.me** to this container.
- By setting **LETSENCRYPT_HOST** and **LETSENCRYPT_EMAIL**, our letsencrypt container will use that
data to create SSL certificates for this service.

## Service: Git repository

And so our final service, the Git repository. I went with [Gogs](https://gogs.io). I originally
liked Gogs because of it's portability, thanks to it being a single binary. Considering I'm running
it inside a container, that doesn't matter as much, but oh well.

Let's take a look at the service definition:

```yaml
  git:
    image: gogs/gogs:0.9.97
    container_name: git
    volumes:
      - gogs:/data
    environment:
      - VIRTUAL_HOST=git.ptrvldz.me
      - VIRTUAL_PORT=3000
      - LETSENCRYPT_HOST=git.ptrvldz.me
      - LETSENCRYPT_EMAIL=webmaster@ptrvldz.me
```

It's all the same as the blog, but there is one difference: **VIRTUAL_PORT**.

If a container only exposes a single port, then our nginx-proxy is smart enough to know it should
forward requests to that port. However, if several ports are exposed by a container, you can
specify which one is correct by setting **VIRTUAL_PORT** to the correct one.

## Volumes

The last section of the file is the volumes block. If you use named volumes, you must define them
in this section, and so we do:

```yaml
volumes:

  ghost:
    external: false
  gogs:
    external: false
  certs:
    external: false
```

Setting **external** to **false** for our volumes will tell Docker Compose that it should create them
if they're not there.

## And we're done

So to reiterate, we have nginx forwarding requests to two applications, each with valid SSL
certificates. With each distinct service in its own container. All this accomplished with 57 lines
of configuration in a single file.

And what if we wanted to add one more service, like that WordPress instance we mentioned earlier?
Probably about 10 more lines and we'd have it routed to by nginx and secured with its own
certificate.

I thank the powers that be for containers.
