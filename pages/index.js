import Head from 'next/head';
import Link from 'next/link';
import Date from '../components/date';
import Layout, { siteTitle } from '../components/layout';
import { getSortedPostsData } from '../lib/posts';
import utilStyles from '../styles/utils.module.css';

export async function getStaticProps() {
  const allPostsData = getSortedPostsData();
  console.log(allPostsData);
  return {
    props: {
      allPostsData,
    },
  };
}

export default function Home({ allPostsData }) {
  return (
    <Layout home>
      <section className="text-center mx-auto">

        <p className="text-lg mb-4">
          the computer whisperer
        </p>

        <div className="text-2xl space-y-4">
          <div>
            <a target="_blank" href="https://twitter.com/outbytheforest">twitter</a>
          </div>

          <div>
            <a target="_blank" href="https://www.linkedin.com/in/peter-valdez/">linkedin</a>
          </div>

          <div>
            <a target="_blank" href="/peter-valdez-march-2023-resume.pdf">resumé 2023</a>
          </div>

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
