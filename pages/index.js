import Head from "next/head";
import Link from "next/link";
import Date from "../components/date";
import Layout, { siteTitle } from "../components/layout";
import { getSortedPostsData } from "../lib/posts";
import utilStyles from "../styles/utils.module.css";

export async function getStaticProps() {
  const allPostsData = getSortedPostsData();
  return {
    props: {
      allPostsData,
    },
  };
}

export default function Home({ allPostsData }) {
  return (
    <Layout home>
      <Head>
        <title>Another Docker cache test pt. 2</title>
      </Head>

      <section className="text-center mx-auto">
        <div className="text-2xl space-y-4">
          <div>
            <a target="_blank" href="https://twitter.com/outbytheforest">
              twitter
            </a>
          </div>

          <div>
            <a target="_blank" href="https://www.linkedin.com/in/peter-valdez/">
              linkedin
            </a>
          </div>

          <div>
            <a target="_blank" href="/peter-valdez-march-2023-resume.pdf">
              resumé
              <br />
              (as of march 2023)
            </a>
          </div>

          <div>
            <a
              target="_blank"
              href="https://www.meetup.com/astoria-tech-meetup/events/292267753/"
            >
              astoria tech meetup #29
              <br />
              (on march 29th, 2023)
            </a>
          </div>

          <hr />
          <hr />

          <h2 className={utilStyles.headingLg}>Blog</h2>

          <ul className={utilStyles.list}>
            {allPostsData.map(({ id, date, title }) => (
              <li className={utilStyles.listItem} key={id}>
                <Link href={`/posts/${id}`}>{title}</Link>
                <br />
                <small className={utilStyles.lightText}>
                  <Date dateString={date} />
                </small>
              </li>
            ))}
          </ul>
        </div>

        <div className="my-10">
          <img src="/images/ubbe.jpg" alt="my cat Ubbe" />
        </div>
      </section>
    </Layout>
  );
}
