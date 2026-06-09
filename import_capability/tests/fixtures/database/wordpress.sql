CREATE TABLE `wp_posts` (
  `ID` bigint unsigned NOT NULL,
  `post_title` text NOT NULL,
  `post_status` varchar(20) NOT NULL
);

CREATE TABLE `wp_options` (
  `option_id` bigint unsigned NOT NULL,
  `option_name` varchar(191) NOT NULL
);
