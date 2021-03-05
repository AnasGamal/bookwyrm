''' test for app action functionality '''
import json
from unittest.mock import patch
import pathlib
from django.test import TestCase
from django.test.client import RequestFactory
import responses

from bookwyrm import models, views
from bookwyrm.settings import USER_AGENT

class ViewsHelpers(TestCase):
    ''' viewing and creating statuses '''
    def setUp(self):
        ''' we need basic test data and mocks '''
        self.factory = RequestFactory()
        self.local_user = models.User.objects.create_user(
            'mouse@local.com', 'mouse@mouse.com', 'mouseword',
            local=True, localname='mouse',
            remote_id='https://example.com/users/mouse',
        )
        self.work = models.Work.objects.create(title='Test Work')
        self.book = models.Edition.objects.create(
            title='Test Book',
            remote_id='https://example.com/book/1',
            parent_work=self.work
        )
        with patch('bookwyrm.models.user.set_remote_server.delay'):
            self.remote_user = models.User.objects.create_user(
                'rat', 'rat@rat.com', 'ratword',
                local=False,
                remote_id='https://example.com/users/rat',
                inbox='https://example.com/users/rat/inbox',
                outbox='https://example.com/users/rat/outbox',
            )
        datafile = pathlib.Path(__file__).parent.joinpath(
            '../data/ap_user.json'
        )
        self.userdata = json.loads(datafile.read_bytes())
        del self.userdata['icon']
        with patch('bookwyrm.models.activitypub_mixin.broadcast_task.delay'):
            self.shelf = models.Shelf.objects.create(
                name='Test Shelf',
                identifier='test-shelf',
                user=self.local_user
            )


    def test_get_edition(self):
        ''' given an edition or a work, returns an edition '''
        self.assertEqual(
            views.helpers.get_edition(self.book.id), self.book)
        self.assertEqual(
            views.helpers.get_edition(self.work.id), self.book)

    def test_get_user_from_username(self):
        ''' works for either localname or username '''
        self.assertEqual(
            views.helpers.get_user_from_username(
                self.local_user, 'mouse'), self.local_user)
        self.assertEqual(
            views.helpers.get_user_from_username(
                self.local_user, 'mouse@local.com'), self.local_user)
        with self.assertRaises(models.User.DoesNotExist):
            views.helpers.get_user_from_username(
                self.local_user, 'mojfse@example.com')


    def test_is_api_request(self):
        ''' should it return html or json '''
        request = self.factory.get('/path')
        request.headers = {'Accept': 'application/json'}
        self.assertTrue(views.helpers.is_api_request(request))

        request = self.factory.get('/path.json')
        request.headers = {'Accept': 'Praise'}
        self.assertTrue(views.helpers.is_api_request(request))

        request = self.factory.get('/path')
        request.headers = {'Accept': 'Praise'}
        self.assertFalse(views.helpers.is_api_request(request))


    def test_get_activity_feed(self):
        ''' loads statuses '''
        rat = models.User.objects.create_user(
            'rat', 'rat@rat.rat', 'password', local=True)

        with patch('bookwyrm.models.activitypub_mixin.broadcast_task.delay'):
            public_status = models.Comment.objects.create(
                content='public status', book=self.book, user=self.local_user)
            direct_status = models.Status.objects.create(
                content='direct', user=self.local_user, privacy='direct')

            rat_public = models.Status.objects.create(
                content='blah blah', user=rat)
            rat_unlisted = models.Status.objects.create(
                content='blah blah', user=rat, privacy='unlisted')
            remote_status = models.Status.objects.create(
                content='blah blah', user=self.remote_user)
            followers_status = models.Status.objects.create(
                content='blah', user=rat, privacy='followers')
            rat_mention = models.Status.objects.create(
                content='blah blah blah', user=rat, privacy='followers')
            rat_mention.mention_users.set([self.local_user])

        statuses = views.helpers.get_activity_feed(
            self.local_user,
            privacy=['public', 'unlisted', 'followers'],
            following_only=True,
            queryset=models.Comment.objects
        )
        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0], public_status)

        statuses = views.helpers.get_activity_feed(
            self.local_user,
            privacy=['public', 'followers'],
            local_only=True
        )
        self.assertEqual(len(statuses), 2)
        self.assertEqual(statuses[1], public_status)
        self.assertEqual(statuses[0], rat_public)

        statuses = views.helpers.get_activity_feed(
            self.local_user, privacy=['direct'])
        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0], direct_status)

        statuses = views.helpers.get_activity_feed(
            self.local_user,
            privacy=['public', 'followers'],
        )
        self.assertEqual(len(statuses), 3)
        self.assertEqual(statuses[2], public_status)
        self.assertEqual(statuses[1], rat_public)
        self.assertEqual(statuses[0], remote_status)

        statuses = views.helpers.get_activity_feed(
            self.local_user,
            privacy=['public', 'unlisted', 'followers'],
            following_only=True
        )
        self.assertEqual(len(statuses), 2)
        self.assertEqual(statuses[1], public_status)
        self.assertEqual(statuses[0], rat_mention)

        rat.followers.add(self.local_user)
        statuses = views.helpers.get_activity_feed(
            self.local_user,
            privacy=['public', 'unlisted', 'followers'],
            following_only=True
        )
        self.assertEqual(len(statuses), 5)
        self.assertEqual(statuses[4], public_status)
        self.assertEqual(statuses[3], rat_public)
        self.assertEqual(statuses[2], rat_unlisted)
        self.assertEqual(statuses[1], followers_status)
        self.assertEqual(statuses[0], rat_mention)


    def test_get_activity_feed_blocks(self):
        ''' feed generation with blocked users '''
        rat = models.User.objects.create_user(
            'rat', 'rat@rat.rat', 'password', local=True)

        with patch('bookwyrm.models.activitypub_mixin.broadcast_task.delay'):
            public_status = models.Comment.objects.create(
                content='public status', book=self.book, user=self.local_user)
            rat_public = models.Status.objects.create(
                content='blah blah', user=rat)

            statuses = views.helpers.get_activity_feed(
                self.local_user, privacy=['public'])
            self.assertEqual(len(statuses), 2)

        # block relationship
        rat.blocks.add(self.local_user)
        statuses = views.helpers.get_activity_feed(
            self.local_user, privacy=['public'])
        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0], public_status)

        statuses = views.helpers.get_activity_feed(
            rat, privacy=['public'])
        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0], rat_public)



    def test_is_bookwyrm_request(self):
        ''' checks if a request came from a bookwyrm instance '''
        request = self.factory.get('', {'q': 'Test Book'})
        self.assertFalse(views.helpers.is_bookwyrm_request(request))

        request = self.factory.get(
            '', {'q': 'Test Book'},
            HTTP_USER_AGENT=\
                "http.rb/4.4.1 (Mastodon/3.3.0; +https://mastodon.social/)"
        )
        self.assertFalse(views.helpers.is_bookwyrm_request(request))

        request = self.factory.get(
            '', {'q': 'Test Book'}, HTTP_USER_AGENT=USER_AGENT)
        self.assertTrue(views.helpers.is_bookwyrm_request(request))


    def test_existing_user(self):
        ''' simple database lookup by username '''
        result = views.helpers.handle_remote_webfinger('@mouse@local.com')
        self.assertEqual(result, self.local_user)

        result = views.helpers.handle_remote_webfinger('mouse@local.com')
        self.assertEqual(result, self.local_user)


    @responses.activate
    def test_load_user(self):
        ''' find a remote user using webfinger '''
        username = 'mouse@example.com'
        wellknown = {
            "subject": "acct:mouse@example.com",
            "links": [{
                "rel": "self",
                "type": "application/activity+json",
                "href": "https://example.com/user/mouse"
            }]
        }
        responses.add(
            responses.GET,
            'https://example.com/.well-known/webfinger?resource=acct:%s' \
                    % username,
            json=wellknown,
            status=200)
        responses.add(
            responses.GET,
            'https://example.com/user/mouse',
            json=self.userdata,
            status=200)
        with patch('bookwyrm.models.user.set_remote_server.delay'):
            result = views.helpers.handle_remote_webfinger('@mouse@example.com')
            self.assertIsInstance(result, models.User)
            self.assertEqual(result.username, 'mouse@example.com')


    def test_handle_reading_status_to_read(self):
        ''' posts shelve activities '''
        shelf = self.local_user.shelf_set.get(identifier='to-read')
        with patch('bookwyrm.models.activitypub_mixin.broadcast_task.delay'):
            views.helpers.handle_reading_status(
                self.local_user, shelf, self.book, 'public')
        status = models.GeneratedNote.objects.get()
        self.assertEqual(status.user, self.local_user)
        self.assertEqual(status.mention_books.first(), self.book)
        self.assertEqual(status.content, 'wants to read')

    def test_handle_reading_status_reading(self):
        ''' posts shelve activities '''
        shelf = self.local_user.shelf_set.get(identifier='reading')
        with patch('bookwyrm.models.activitypub_mixin.broadcast_task.delay'):
            views.helpers.handle_reading_status(
                self.local_user, shelf, self.book, 'public')
        status = models.GeneratedNote.objects.get()
        self.assertEqual(status.user, self.local_user)
        self.assertEqual(status.mention_books.first(), self.book)
        self.assertEqual(status.content, 'started reading')

    def test_handle_reading_status_read(self):
        ''' posts shelve activities '''
        shelf = self.local_user.shelf_set.get(identifier='read')
        with patch('bookwyrm.models.activitypub_mixin.broadcast_task.delay'):
            views.helpers.handle_reading_status(
                self.local_user, shelf, self.book, 'public')
        status = models.GeneratedNote.objects.get()
        self.assertEqual(status.user, self.local_user)
        self.assertEqual(status.mention_books.first(), self.book)
        self.assertEqual(status.content, 'finished reading')

    def test_handle_reading_status_other(self):
        ''' posts shelve activities '''
        with patch('bookwyrm.models.activitypub_mixin.broadcast_task.delay'):
            views.helpers.handle_reading_status(
                self.local_user, self.shelf, self.book, 'public')
        self.assertFalse(models.GeneratedNote.objects.exists())

    def test_object_visible_to_user(self):
        ''' does a user have permission to view an object '''
        obj = models.Status.objects.create(
            content='hi', user=self.remote_user, privacy='public')
        self.assertTrue(
            views.helpers.object_visible_to_user(self.local_user, obj))

        obj = models.Shelf.objects.create(
            name='test', user=self.remote_user, privacy='unlisted')
        self.assertTrue(
            views.helpers.object_visible_to_user(self.local_user, obj))

        obj = models.Status.objects.create(
            content='hi', user=self.remote_user, privacy='followers')
        self.assertFalse(
            views.helpers.object_visible_to_user(self.local_user, obj))

        obj = models.Status.objects.create(
            content='hi', user=self.remote_user, privacy='direct')
        self.assertFalse(
            views.helpers.object_visible_to_user(self.local_user, obj))

        obj = models.Status.objects.create(
            content='hi', user=self.remote_user, privacy='direct')
        obj.mention_users.add(self.local_user)
        self.assertTrue(
            views.helpers.object_visible_to_user(self.local_user, obj))

    def test_object_visible_to_user_follower(self):
        ''' what you can see if you follow a user '''
        self.remote_user.followers.add(self.local_user)
        obj = models.Status.objects.create(
            content='hi', user=self.remote_user, privacy='followers')
        self.assertTrue(
            views.helpers.object_visible_to_user(self.local_user, obj))

        obj = models.Status.objects.create(
            content='hi', user=self.remote_user, privacy='direct')
        self.assertFalse(
            views.helpers.object_visible_to_user(self.local_user, obj))

        obj = models.Status.objects.create(
            content='hi', user=self.remote_user, privacy='direct')
        obj.mention_users.add(self.local_user)
        self.assertTrue(
            views.helpers.object_visible_to_user(self.local_user, obj))

    def test_object_visible_to_user_blocked(self):
        ''' you can't see it if they block you '''
        self.remote_user.blocks.add(self.local_user)
        obj = models.Status.objects.create(
            content='hi', user=self.remote_user, privacy='public')
        self.assertFalse(
            views.helpers.object_visible_to_user(self.local_user, obj))

        obj = models.Shelf.objects.create(
            name='test', user=self.remote_user, privacy='unlisted')
        self.assertFalse(
            views.helpers.object_visible_to_user(self.local_user, obj))
